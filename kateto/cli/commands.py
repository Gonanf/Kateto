from __future__ import annotations

import argparse
import asyncio  # noqa: ANYIO_OK
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
try:
    from typing import override
except ImportError:
    from typing_extensions import override

from cliff.command import Command
from loguru import logger

from kateto.cli.agency_convert import _resolve_source, convert_agency_pack
from kateto.cli.registry import register_command
from kateto.core.config import load_config
from kateto.core.discovery import LiveAssemblyConfigurationError as EventRuntimeConfigurationError
from kateto.core.exceptions import ConfigError
from kateto.run_mode import run_event_runtime

from kateto.voices.factory import _PROFILES

_CONFIG_ERRORS: tuple[type[Exception], ...] = (ConfigError,)


class ConfigCheck(Command):
    """Validate the kateto configuration."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        try:
            loaded = load_config()
        except _CONFIG_ERRORS as error:
            _ = self.app.stderr.write(f"config check: {error}\n")
            return 2
        _ = self.app.stdout.write(f"config check: ok ({loaded.paths.config_dir})\n")
        return 0


class Run(Command):
    """Run the event runtime."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("--trace", action="store_true", help="log every bus event to stderr")
        _ = parser.add_argument("--trace-events", metavar="NAME", action="append", default=[], help="only trace events with this name (repeatable)")
        _ = parser.add_argument("--trace-voice", metavar="VOICE", action="append", default=[], help="only trace events touching this voice (repeatable)")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        trace = bool(getattr(parsed_args, "trace", False))
        trace_events = tuple(str(event) for event in getattr(parsed_args, "trace_events", ()))
        trace_voice = tuple(str(voice) for voice in getattr(parsed_args, "trace_voice", ()))
        try:
            loaded = load_config()
            asyncio.run(
                run_event_runtime(
                    loaded,
                    trace=trace,
                    trace_events=trace_events,
                    trace_voice=trace_voice,
                )
            )
        except (*_CONFIG_ERRORS, EventRuntimeConfigurationError) as error:
            _ = self.app.stderr.write(f"run: {error}\n")
            return 2
        return 0


class Smoke(Command):
    """Run the bounded smoke test suite."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        return subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "kateto/tests/test_event_bus.py", "kateto/tests/test_plugin_manager.py",
                "kateto/tests/test_config.py", "kateto/tests/test_workflow.py",
                "kateto/tests/test_storage.py", "-q",
            ],
            check=False,
        ).returncode


class Compile(Command):
    """Install and compile pywhispercpp / llama-cpp-python bindings with chosen acceleration."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument(
            "target",
            choices=["whisper", "llama", "all"],
            default="all",
            nargs="?",
            help="target to install: whisper, llama, or all (default: all)",
        )
        _ = parser.add_argument(
            "--backend",
            choices=["vulkan", "cuda", "cpu", "metal", "openblas"],
            default="vulkan",
            help="hardware acceleration backend (default: vulkan)",
        )
        _ = parser.add_argument(
            "--cmake-args",
            action="append",
            default=[],
            help="extra CMake arguments (repeatable)",
        )
        _ = parser.add_argument(
            "--jobs",
            type=int,
            default=1,
            help="maximum parallel compiler jobs to prevent OOM (default: 1, max: 2)",
        )
        _ = parser.add_argument(
            "--no-prebuilt",
            action="store_true",
            help="force source compilation instead of using prebuilt wheels",
        )
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        from kateto.tools.compiler import CompilerOptions, compile_llama, compile_whisper

        target = str(getattr(parsed_args, "target", "all"))
        backend = str(getattr(parsed_args, "backend", "vulkan"))
        cmake_args = [str(arg) for arg in getattr(parsed_args, "cmake_args", [])]
        jobs = int(getattr(parsed_args, "jobs", 1))
        prefer_prebuilt = not bool(getattr(parsed_args, "no_prebuilt", False))

        opts = CompilerOptions(
            backend=backend,
            cmake_args=cmake_args,
            jobs=jobs,
            prefer_prebuilt=prefer_prebuilt,
        )

        code = 0
        if target in ("whisper", "all"):
            code = compile_whisper(opts)
            if code != 0:
                return code
        if target in ("llama", "all"):
            code = compile_llama(opts)
            if code != 0:
                return code
        return code


@dataclass(frozen=True, slots=True)
class _Installed:
    voices: list[str]
    skills: list[str]


def _install_pack(*, source: str, config_dir: Path, force: bool) -> _Installed:
    """Clone-or-pull a pack (git URL or local path) and copy voices/ + skills/ in.

    A pack is a dir tree with `voices/<id>/SOUL.md` and `skills/<name>/SKILL.md`.
    Those layouts are already consumed by create_voice() and _ensure_voice_skills(),
    so copying them into config_dir is the whole job. Copy-missing unless --force.
    """
    pack_dir = _resolve_source(source, cache_root=Path.home() / ".cache" / "kateto" / "packs")

    installed_voices: list[str] = []
    installed_skills: list[str] = []
    for kind, sink in (("voices", installed_voices), ("skills", installed_skills)):
        src = pack_dir / kind
        if not src.is_dir():
            continue
        dst = config_dir / kind
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if not item.is_dir():
                continue
            target = dst / item.name
            if target.exists() and not force:
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
            sink.append(item.name)
    return _Installed(voices=installed_voices, skills=installed_skills)


class Install(Command):
    """Install a voice/skill pack, or convert an agency-agents repo with --from-agency."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("source", help="git URL or local path to a pack (or agency-agents repo with --from-agency)")
        _ = parser.add_argument("--force", action="store_true", help="overwrite existing voices/skills")
        _ = parser.add_argument("--from-agency", action="store_true", help="treat source as an agency-agents repo (division dirs of .md agents)")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        source = str(getattr(parsed_args, "source"))
        force = bool(getattr(parsed_args, "force", False))
        from_agency = bool(getattr(parsed_args, "from_agency", False))
        try:
            loaded = load_config()
        except _CONFIG_ERRORS as error:
            _ = self.app.stderr.write(f"install: {error}\n")
            return 2
        try:
            if from_agency:
                repo_dir = _resolve_source(source, cache_root=Path.home() / ".cache" / "kateto" / "agency")
                with tempfile.TemporaryDirectory(prefix="kateto-agency-") as tmp:
                    converted = convert_agency_pack(repo_dir, Path(tmp), force=force)
                    if not converted:
                        _ = self.app.stdout.write("install: no agency agents converted\n")
                        return 0
                    result = _install_pack(source=tmp, config_dir=loaded.paths.config_dir, force=force)
            else:
                result = _install_pack(source=source, config_dir=loaded.paths.config_dir, force=force)
        except (subprocess.CalledProcessError, OSError) as error:
            _ = self.app.stderr.write(f"install: {error}\n")
            return 2
        if not result.voices and not result.skills:
            _ = self.app.stdout.write("install: nothing installed (pack has no voices/ or skills/)\n")
            return 0
        for name in result.voices:
            _ = self.app.stdout.write(f"installed voice: {name}\n")
        for name in result.skills:
            _ = self.app.stdout.write(f"installed skill: {name}\n")
        return 0


class Setup(Command):
    """Interactively configure models/endpoints (deep-merge, secrets to file)."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        from kateto.cli.setup_wizard import run_setup

        try:
            return run_setup()
        except (KeyboardInterrupt, EOFError):
            _ = self.app.stderr.write("setup: aborted\n")
            return 1


class Doctor(Command):
    """Report config, models, servers, VAD and masked API keys."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        from dotenv import load_dotenv

        from kateto.cli.doctor import doctor_report
        from kateto.core.config import resolve_config_dir

        config_dir = resolve_config_dir()
        _ = load_dotenv(dotenv_path=config_dir / ".env", override=False)
        _ = load_dotenv(dotenv_path=config_dir / "secrets" / ".env", override=False)
        config_file = config_dir / "config.toml"
        config_text = config_file.read_text() if config_file.is_file() else None
        exit_code, results = doctor_report(config_text)
        for result in results:
            status = "ok" if result.ok else "FAIL"
            _ = self.app.stdout.write(f"[{status}] {result.name}: {result.detail}\n")
        return exit_code


class Debate(Command):
    """Run the autonomous BATE DEBATE DE BATE DE CHOCOLATE multi-voice trial."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("--topic", default=None, help="tema del juicio (si no, lo genera el Juez)")
        _ = parser.add_argument("--judge", default="jane", help="voz jueza (default: jane)")
        _ = parser.add_argument("--voices", default="whisperer,doktor,conquest",
                                help="debaters separados por coma (default: whisperer,doktor,conquest)")
        _ = parser.add_argument("--rounds", type=int, default=1, help="turnos de argumento por debater")
        _ = parser.add_argument("--infinite", action="store_true", help="modo infinito: reinicia con voces/tema nuevos")
        _ = parser.add_argument("--max-debates", type=int, default=3, help="max juicios en modo infinito")
        _ = parser.add_argument("--self-test", "--mock", action="store_true",
                                help="usa MockProvider (sin red) y corre un juicio completo offline")
        _ = parser.add_argument("--registry-dir", default=None, help="directorio de registro (default: <config>/bate_debate/registry)")
        _ = parser.add_argument("--list-voices", action="store_true", help="lista las voces de Kateto y sale")
        _ = parser.add_argument("--overlay", action="store_true",
                                help="best-effort: reenvia cada turno al visual overlay por WS (no fatal)")
        _ = parser.add_argument("--delay", type=float, default=None,
                                help="pausa en segundos entre argumentos (default: 3.5s para debates reales, 0.0s en mock)")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        args = parsed_args  # type: ignore[assignment]
        if bool(getattr(args, "list_voices", False)):
            for vid, prof in _PROFILES.items():
                _ = self.app.stdout.write(f"{vid:12s} {prof.display_name:12s} {prof.role.value}\n")
            return 0

        try:
            from kateto.plugins.bate_debate import run_debate
            from kateto.plugins.bate_debate.mock import MockProvider
        except Exception as error:  # noqa: BLE001
            _ = self.app.stderr.write(f"debate: no se pudo importar el motor: {error}\n")
            return 2

        judge = str(getattr(args, "judge", "jane")).casefold()
        debaters = [v.strip().casefold() for v in str(getattr(args, "voices", "")).split(",") if v.strip()]
        if judge in debaters:
            debaters = [v for v in debaters if v != judge]
        if not debaters:
            debaters = ["whisperer", "doktor", "conquest"]

        cfg_dir = None
        registry_dir = Path(getattr(args, "registry_dir")) if getattr(args, "registry_dir") else None
        try:
            loaded = load_config()
            cfg_dir = loaded.paths.config_dir
            if registry_dir is None:
                registry_dir = cfg_dir / "bate_debate" / "registry"
        except Exception:  # noqa: BLE001
            cfg_dir = Path.home() / ".config" / "kateto"
            if registry_dir is None:
                registry_dir = cfg_dir / "bate_debate" / "registry"

        use_mock = bool(getattr(args, "self_test", False))

        # Optional overlay broadcaster (best-effort, non-fatal).
        overlay_ws = None
        if bool(getattr(args, "overlay", False)):
            overlay_ws = _make_overlay_broadcaster()

        def on_speak(voice_id: str, role: str, phase: str, text: str) -> None:
            prof = _PROFILES.get(voice_id)
            vname = prof.display_name if prof else voice_id.title()
            self.app.stdout.write(f"[{vname} • {phase.upper()}]: {text}\n\n")
            self.app.stdout.flush()
            if overlay_ws is not None:
                try:
                    overlay_ws(voice_id, role, phase, text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("overlay broadcast failed: {}", exc)

        raw_delay = getattr(args, "delay", None)
        if raw_delay is not None:
            arg_delay = float(raw_delay)
        else:
            arg_delay = 0.0 if use_mock else 0.5

        async def _run() -> list:
            if use_mock:
                factory = lambda vid: MockProvider()  # noqa: E731
                owner = None
                manager = None
            else:
                factory = _real_provider_factory()
                owner = None
                manager = None
                try:
                    from kateto.run_mode import build_runtime_owner
                    owner = build_runtime_owner(loaded)
                    await owner.start()
                    manager = owner.manager
                except Exception as exc:
                    logger.warning("No se pudo iniciar el runtime de eventos para el debate, usando proveedor directo: {}", exc)
                    owner = None
                    manager = None

            try:
                return await run_debate(
                    judge=judge,
                    debaters=debaters,
                    topic=str(getattr(args, "topic")) if getattr(args, "topic") else None,
                    provider_factory=factory,
                    manager=manager,
                    rounds=int(getattr(args, "rounds", 1)),
                    infinite=bool(getattr(args, "infinite", False)),
                    max_debates=int(getattr(args, "max_debates", 3)),
                    registry_dir=registry_dir,
                    on_speak=on_speak,
                    delay_between_arguments=arg_delay,
                    config_dir=cfg_dir,
                )
            finally:
                if owner is not None:
                    try:
                        await owner.stop()
                    except Exception:
                        pass

        try:
            records = asyncio.run(_run())
        except KeyboardInterrupt:
            _ = self.app.stdout.write("debate: interrumpido por el usuario\n")
            return 0
        except Exception as error:  # noqa: BLE001
            _ = self.app.stderr.write(f"debate: error en el juicio: {error}\n")
            return 2
        finally:
            if overlay_ws is not None:
                overlay_ws.close() if hasattr(overlay_ws, "close") else None

        for rec in records:
            _ = self.app.stdout.write(f"Juicio: {rec.topic}\n  registro: {rec.registry_md}\n  jsonl:   {rec.registry_jsonl}\n")
            _ = self.app.stdout.write(f"  veredicto: {rec.verdict[:160]}\n")
        return 0


def _real_provider_factory():
    """Build a real OpenAI-compatible provider factory from kateto config / env."""
    import os

    from kateto.voices.base import OpenAICompatibleProvider

    endpoint = "http://localhost:11434/v1"
    model = "Kateto"
    api_key = "sk-no"
    backend = None
    rwkv_model_path = None
    rwkv_states_dir = None
    rwkv_vocab_path = None
    rwkv_temp = 0.7
    rwkv_top_p = 0.7
    try:
        loaded = load_config()
        vllm = loaded.settings.plugin.get("voice_llm") if loaded.settings.plugin else None
        if vllm is not None:
            if isinstance(vllm, dict):
                endpoint = vllm.get("endpoint") or endpoint
                model = vllm.get("model") or model
                api_key = vllm.get("api_key") or api_key
                backend = vllm.get("backend")
                rwkv_model_path = vllm.get("model_path") or (vllm.get("model") if vllm.get("model", "").endswith(".pth") else None)
                rwkv_states_dir = vllm.get("states_dir")
                rwkv_vocab_path = vllm.get("vocab_path") or vllm.get("vocab")
                if "temperature" in vllm:
                    rwkv_temp = float(vllm["temperature"])
                if "top_p" in vllm:
                    rwkv_top_p = float(vllm["top_p"])
                if "max_tokens" in vllm and vllm["max_tokens"]:
                    max_tokens = int(vllm["max_tokens"])
            else:
                endpoint = getattr(vllm, "endpoint", None) or endpoint
                model = getattr(vllm, "model", None) or model
                api_key = getattr(vllm, "api_key", None) or api_key
                backend = getattr(vllm, "backend", None)
                m = getattr(vllm, "model", None)
                rwkv_model_path = getattr(vllm, "model_path", None) or (m if m and m.endswith(".pth") else None)
                rwkv_states_dir = getattr(vllm, "states_dir", None)
                rwkv_vocab_path = getattr(vllm, "vocab_path", None) or getattr(vllm, "vocab", None)
                if hasattr(vllm, "temperature") and getattr(vllm, "temperature", None) is not None:
                    rwkv_temp = float(getattr(vllm, "temperature"))
                if hasattr(vllm, "top_p") and getattr(vllm, "top_p", None) is not None:
                    rwkv_top_p = float(getattr(vllm, "top_p"))
                if hasattr(vllm, "max_tokens") and getattr(vllm, "max_tokens", None) is not None:
                    max_tokens = int(getattr(vllm, "max_tokens"))
    except Exception:  # noqa: BLE001
        pass

    endpoint = os.environ.get("KATETO_LLM_ENDPOINT") or endpoint
    model = os.environ.get("KATETO_LLM_MODEL") or model
    api_key = os.environ.get("KATETO_LLM_API_KEY") or api_key
    max_tokens = int(os.environ.get("KATETO_LLM_MAX_TOKENS", str(max_tokens if 'max_tokens' in locals() else 256)))

    provider_type = (os.environ.get("KATETO_PROVIDER") or backend or "rwkv").casefold()
    if provider_type == "rwkv":
        try:
            from kateto.providers.rwkv_rocm import RWKVROCmProvider
            rwkv_cache: dict[str, RWKVROCmProvider] = {}

            def rwkv_factory(voice_id: str) -> RWKVROCmProvider:
                if voice_id not in rwkv_cache:
                    rwkv_cache[voice_id] = RWKVROCmProvider(
                        voice_id=voice_id,
                        model_path=rwkv_model_path,
                        states_dir=rwkv_states_dir,
                        vocab_path=rwkv_vocab_path,
                        temperature=rwkv_temp,
                        top_p=rwkv_top_p,
                        max_tokens=max_tokens,
                    )
                return rwkv_cache[voice_id]

            return rwkv_factory
        except Exception as exc:
            logger.warning("No se pudo inicializar RWKVROCmProvider, usando OpenAI fallback: {}", exc)

    cache: dict[str, OpenAICompatibleProvider] = {}

    def factory(voice_id: str) -> OpenAICompatibleProvider:
        if voice_id not in cache:
            cache[voice_id] = OpenAICompatibleProvider(
                model=model, endpoint=endpoint, api_key=api_key, max_tokens=max_tokens
            )
        return cache[voice_id]

    return factory


def _make_overlay_broadcaster():
    """Best-effort WS broadcaster to a running `kateto run` overlay endpoint.

    The broadcaster owns its WebSocket in a dedicated background thread with its
    own event loop, so `on_speak` can schedule sends safely from whatever loop is
    currently running the debate (the previous implementation called
    ``loop.run_until_complete`` from inside an already-running loop, which raised
    "Cannot run the event loop while another loop is running" and dropped every
    turn).
    """
    import asyncio
    import os
    import threading

    url = os.environ.get("KATETO_OVERLAY_WS")
    if not url:
        port = 8080
        try:
            import tomllib
            from kateto.core.config import load_config
            cfg = load_config()
            raw = tomllib.loads(cfg.paths.config_file.read_text(encoding="utf-8"))
            hs = raw.get("http_server") or (raw.get("plugin") or {}).get("http_server") or {}
            if isinstance(hs, dict):
                port = int(hs.get("port", 8080))
            elif hasattr(hs, "port"):
                port = int(hs.port)
            url = f"ws://localhost:{port}/ws/overlay"
        except Exception:  # noqa: BLE001
            url = "ws://localhost:8080/ws/overlay"

    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("overlay: modulo 'websockets' no disponible; se omite el broadcast")
        return None

    loop = asyncio.new_event_loop()

    class _Broadcaster:
        def __init__(self) -> None:
            self._ws = None
            self._ready = threading.Event()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            self._ready.wait(timeout=5)

        def _run(self) -> None:
            asyncio.set_event_loop(loop)

            async def _connect():
                self._ws = await websockets.connect(
                    url,
                    ping_interval=15,
                    ping_timeout=15,
                    open_timeout=4,
                    close_timeout=4,
                )

            try:
                loop.run_until_complete(_connect())
            except Exception as exc:  # noqa: BLE001
                logger.warning("overlay: no se pudo conectar a {}: {}", url, exc)
            finally:
                self._ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    tasks = asyncio.all_tasks(loop)
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        loop.run_until_complete(
                            asyncio.gather(*tasks, return_exceptions=True)
                        )
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                finally:
                    loop.close()

        def _is_open(self) -> bool:
            if self._ws is None:
                return False
            state = getattr(self._ws, "state", None)
            if state is not None:
                return getattr(state, "name", "") == "OPEN" or state == 1
            return not getattr(self._ws, "closed", False)

        def __call__(self, voice_id, role, phase, text):
            msg = {
                "event": "debate",
                "type": "subtitle",
                "voice_id": voice_id,
                "role": role,
                "phase": phase,
                "text": text,
                "rms": 0.0,
                "is_speaking": True,
                "data": {
                    "text": text,
                    "voice_id": voice_id,
                    "role": role,
                    "phase": phase,
                },
            }
            fut = asyncio.run_coroutine_threadsafe(self._safe_send(msg), loop)
            try:
                fut.result(timeout=6)
            except Exception as exc:  # noqa: BLE001
                logger.warning("overlay send failed: {}", exc)

        async def _safe_send(self, msg):
            for attempt in range(2):
                try:
                    if not self._is_open():
                        self._ws = await websockets.connect(
                            url,
                            ping_interval=15,
                            ping_timeout=15,
                            open_timeout=4,
                            close_timeout=2,
                        )
                    await self._ws.send(json.dumps(msg))
                    return
                except Exception as exc:  # noqa: BLE001
                    self._ws = None
                    if attempt == 0:
                        logger.info("overlay send hiccup ({}), reconectando...", exc)
                    else:
                        logger.warning("overlay send failed: {}", exc)

        def close(self) -> None:
            async def _close_ws():
                if self._ws is not None:
                    try:
                        await asyncio.wait_for(self._ws.close(), timeout=1.0)
                    except Exception:
                        pass
                    self._ws = None

            if loop.is_running():
                try:
                    fut = asyncio.run_coroutine_threadsafe(_close_ws(), loop)
                    fut.result(timeout=2)
                except Exception:
                    pass
                loop.call_soon_threadsafe(loop.stop)
            self._thread.join(timeout=3)

    return _Broadcaster()


register_command("config check", ConfigCheck)
register_command("run", Run)
register_command("smoke", Smoke)
register_command("compile", Compile)
register_command("install", Install)
register_command("setup", Setup)
register_command("doctor", Doctor)
register_command("debate", Debate)
