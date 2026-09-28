"""End-of-turn (EOT) two-stage text gate (fail-open).

Runs ``clasificador_hibrido.py`` (sibling kateto-eot2 repo, read-only) as a
single long-lived child process: stdin line -> stdout JSON line per
INTEGRACION.md. Any error (missing script, dead process, timeout, bad JSON)
returns RESPOND with ``failed_open=True`` — identical to today's behavior.
Never raises to the bus.
"""

from __future__ import annotations

import asyncio
import json
import os
import select
import subprocess
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger

from kateto.core.event import TranscriptionData
from kateto.core.plugin import Plugin

log = logger

EOT2_DIR = Path("/run/media/chaos/secundario/proyectos/kateto-eot2")
DEFAULT_SCRIPT = EOT2_DIR / "clasificador_hibrido.py"
MAX_RESTARTS = 3


class EotAction(StrEnum):
    RESPOND = "respond"
    WAIT = "wait"
    SUPPRESS = "suppress"


@dataclass
class EotResult:
    action: EotAction = EotAction.RESPOND
    wait_score: float = 0.0
    wait_thr: float = 0.0
    no_response_score: float = 0.0
    no_response_thr: float = 0.0
    failed_open: bool = False


def _fail_open() -> EotResult:
    return EotResult(action=EotAction.RESPOND, failed_open=True)


def _opt(settings: Any | None, key: str, default: Any) -> Any:
    if settings is None:
        return default
    value = getattr(settings, key, None)
    if value is None:
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                value = getter(key, None)
            except Exception:  # noqa: BLE001
                value = None
    return default if value is None else value


def _resolve_etapa2(etapa2: str) -> tuple[list[str], bool]:
    """Single source of truth: extra CLI args + whether the variant is servable.

    ``ft`` has an exported head (modelos/cabeza_etapa2_ft.npz) and runs.
    ``base`` has no exported ONNX head: it needs a second forward of the
    *pretrained* distilbert encoder, but clasificador_hibrido.py accepts a
    single --onnx and does exactly one forward — so base is unavailable
    (gate off, fail-open). Never map base onto the ft head: the upstream
    report discarded that combo (F1 0.671).
    """
    modelos = EOT2_DIR / "modelos"
    if etapa2 == "ft":
        cabeza = modelos / "cabeza_etapa2_ft.npz"
        if cabeza.exists():
            return ["--cabeza", str(cabeza)], True
        log.warning(
            "eot_gate: etapa2=ft but {} missing, gate unavailable (fail-open)",
            cabeza,
        )
        return [], False
    # ponytail: base is not servable, so base == gate off; add a second --onnx forward when the pretrained encoder is exported
    log.warning(
        "eot_gate: etapa2=base is not servable: no exported ONNX head exists "
        "for it (needs a second forward of the pretrained distilbert encoder, "
        "so it cannot run under the single---onnx protocol of "
        "clasificador_hibrido.py); export the pretrained distilbert encoder "
        "to ONNX next to the existing ones in {}/modelos/ or set etapa2=ft "
        "(EOT_ETAPA2=ft)",
        EOT2_DIR,
    )
    return [], False


def _etapa2_args(etapa2: str) -> list[str]:
    """Back-compat wrapper: args only (usability lives in _resolve_etapa2)."""
    args, _usable = _resolve_etapa2(etapa2)
    return args


class EotClassifierClient:
    """Owns the clasificador_hibrido.py child process (spawn once)."""

    def __init__(
        self,
        *,
        python: str = "python3",
        script: str | Path = DEFAULT_SCRIPT,
        extra_args: tuple[str, ...] | list[str] = (),
        timeout: float = 1.0,
    ) -> None:
        self._cmd = [python, str(script), *extra_args]
        self._script = str(script)
        self._timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._restarts = 0
        self._dead = False

    @property
    def script_missing(self) -> bool:
        return not Path(self._script).exists()

    def _spawn(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            return True
        except Exception as error:  # noqa: BLE001
            log.warning("eot_gate: spawn failed ({}): {}", self._cmd, error)
            return False

    def _ensure_alive(self) -> bool:
        if self._dead:
            return False
        proc = self._proc
        if proc is not None and proc.poll() is None:
            return True
        if self._restarts >= MAX_RESTARTS:
            self._dead = True
            log.warning("eot_gate: classifier died {}x, staying fail-open", self._restarts)
            return False
        self._restarts += 1
        self._stop_proc()
        if not self._spawn():
            return False
        log.info("eot_gate: classifier (re)started (attempt {})", self._restarts)
        return True

    def classify_sync(self, text: str) -> EotResult:
        if not text or not text.strip():
            return EotResult(action=EotAction.RESPOND)
        if self.script_missing:
            return _fail_open()
        with self._lock:
            if not self._ensure_alive():
                return _fail_open()
            assert self._proc is not None and self._proc.stdin is not None
            assert self._proc.stdout is not None
            try:
                self._proc.stdin.write(text.strip().replace("\n", " ") + "\n")
                self._proc.stdin.flush()
                ready, _, _ = select.select([self._proc.stdout], [], [], self._timeout)
                if not ready:
                    raise TimeoutError(f"no reply in {self._timeout}s")
                line = self._proc.stdout.readline()
                if not line:
                    raise BrokenPipeError("classifier stdout closed")
                return _parse(line)
            except Exception as error:  # noqa: BLE001
                log.warning("eot_gate: classify failed ({}), fail-open", error)
                self._restarts += 1
                self._stop_proc()
                if self._restarts >= MAX_RESTARTS:
                    self._dead = True
                return _fail_open()

    def _stop_proc(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        with self._lock:
            self._stop_proc()


def _head(payload: object, key: str) -> tuple[bool, float, float]:
    if not isinstance(payload, dict):
        return False, 0.0, 0.0
    try:
        return (
            bool(payload.get("decision", False)),
            float(payload.get("score", 0.0)),
            float(payload.get("thr", 0.0)),
        )
    except (TypeError, ValueError):
        return False, 0.0, 0.0


def _parse(line: str) -> EotResult:
    try:
        payload = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return _fail_open()
    wait_dec, wait_score, wait_thr = _head(payload.get("wait"), "wait")
    nr_dec, nr_score, nr_thr = _head(payload.get("no_response"), "no_response")
    action = (
        EotAction.WAIT
        if wait_dec
        else EotAction.SUPPRESS if nr_dec else EotAction.RESPOND
    )
    return EotResult(
        action=action,
        wait_score=wait_score,
        wait_thr=wait_thr,
        no_response_score=nr_score,
        no_response_thr=nr_thr,
    )


@dataclass
class _EotGateState:
    last_text: str = ""
    results: list[EotResult] = field(default_factory=list)


class EotGate(Plugin):
    """EOT gate plugin: caches transcriptions, classifies text on demand."""

    def __init__(self, settings: Any | None = None) -> None:
        super().__init__("eot_gate")
        self._enabled_by_config = bool(_opt(settings, "enabled", False))
        timeout = float(_opt(settings, "timeout", 1.0))
        python = str(_opt(settings, "python", "python3"))
        script = str(_opt(settings, "script", str(DEFAULT_SCRIPT)))
        etapa2 = str(
            os.environ.get("EOT_ETAPA2", _opt(settings, "etapa2", "base") or "base")
        ).lower()
        if etapa2 not in ("base", "ft"):
            log.warning("eot_gate: unknown EOT_ETAPA2={!r}, falling back to base", etapa2)
            etapa2 = "base"
        self._etapa2 = etapa2
        extra_args, self._etapa2_usable = _resolve_etapa2(etapa2)
        self._client = EotClassifierClient(
            python=python,
            script=script,
            extra_args=extra_args,
            timeout=timeout,
        )
        self._state = _EotGateState()

    @property
    def available(self) -> bool:
        """False when disabled, script missing, or etapa2 not servable."""
        return (
            self._enabled_by_config
            and self._etapa2_usable
            and not self._client.script_missing
        )

    @property
    def etapa2(self) -> str:
        return self._etapa2

    async def initialize(self) -> None:
        try:
            self.required_manager.register_event("transcription", TranscriptionData)
        except Exception:  # noqa: BLE001
            pass  # already registered (e.g. by TurnGate)

    async def on_transcription(self, data: TranscriptionData) -> None:
        self._state.last_text = data.text

    def classify(self, text: str) -> EotResult:
        """Sync wrapper: fail-open RESPOND when unavailable, never raises."""
        if not self.available:
            return _fail_open()
        try:
            return self._client.classify_sync(text)
        except Exception as error:  # noqa: BLE001
            log.warning("eot_gate: classify raised ({}), fail-open", error)
            return _fail_open()

    async def aclassify(self, text: str) -> EotResult:
        """Async wrapper (blocking child I/O runs in a thread)."""
        try:
            return await asyncio.to_thread(self.classify, text)
        except Exception as error:  # noqa: BLE001
            log.warning("eot_gate: aclassify raised ({}), fail-open", error)
            return _fail_open()

    async def disable(self) -> None:
        self._client.stop()
