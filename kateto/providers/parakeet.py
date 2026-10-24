from __future__ import annotations

import asyncio
import json
import tempfile
import wave
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path
from typing import Final, Self

import httpx
from loguru import logger

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.exceptions import ProviderError
from kateto.providers._local import _capture
from kateto.providers.errors import UnsupportedAudioPayload

# ponytail: verified machine paths for the parakeet (CrispASR) engines. Kept as
# defaults so `motor` alone selects the quality/latency profile; override via the
# `bin` / `model` plugin settings if your binaries/models live elsewhere.
_DEFAULT_BIN = "/run/media/chaos/secundario/proyectos/crispasr/crispasr-linux-x86_64-vulkan/crispasr"
_DEFAULT_MODEL_BY_MOTOR = {
    "ultra": "/run/media/chaos/secundario/proyectos/redux-gguf/models/parakeet-ultra-q8_0.gguf",
    "redux": "/run/media/chaos/secundario/proyectos/redux-gguf/models/parakeet-redux-q8_0.gguf",
}
_DEFAULT_MOTOR = "ultra"
_DEFAULT_TRANSPORT = "server"
_DEFAULT_HOST: Final = "127.0.0.1"
_DEFAULT_PORT: Final = 8098
_DEFAULT_SERVER_PATH: Final = "/v1/audio/transcriptions"
_DEFAULT_TIMEOUT_S = 120.0

# Streaming (CrispASR `--stream`) tuning. `step` is the accumulation window that
# bounds how often a partial is emitted; `silence` is how long CrispASR waits
# after speech ends before closing the utterance with a `final`.
_DEFAULT_STREAM_STEP_MS = 500
_DEFAULT_STREAM_SILENCE_MS = 600
_DEFAULT_MAX_RESTARTS = 3
_DEFAULT_FINAL_WAIT_S = 30.0

# GPU backends accepted for the CLI `--gpu-backend` flag. Used to disambiguate a
# legacy `backend = "vulkan"` config from the transport-selecting `backend`.
_GPU_BACKENDS = {"vulkan", "cuda", "metal", "openblas"}


class ParakeetProvider:
    """Local CrispASR (parakeet) STT provider via a fresh CLI invocation.

    Same contract as the whisper providers (async lifecycle + ``transcribe``).
    The CLI loads the model per invocation, so a session turn pays full model
    load. For short voice-runtime audio prefer the ``server`` transport
    (:class:`ParakeetServerProvider`) which keeps the model resident.
    Fail-open: a missing binary/model or a hang surfaces as a raised error that
    the audio_processor plugin swallows into empty output, keeping the voice
    flow alive.
    """

    def __init__(self, settings: PluginSettings) -> None:
        self._settings = settings
        self._bin = getattr(settings, "bin", None) or _DEFAULT_BIN
        motor = getattr(settings, "motor", None) or _DEFAULT_MOTOR
        self._motor = motor if motor in _DEFAULT_MODEL_BY_MOTOR else _DEFAULT_MOTOR
        self._model = getattr(settings, "model", None) or _DEFAULT_MODEL_BY_MOTOR[self._motor]
        # `gpu_backend` is the canonical GPU flag since `backend` now selects the
        # transport (server|cli). Fall back to a legacy `backend = "vulkan"` value.
        gpu_backend = getattr(settings, "gpu_backend", None) or getattr(settings, "backend", None)
        self._backend = gpu_backend if gpu_backend in _GPU_BACKENDS else "vulkan"
        self._device = getattr(settings, "device", None)
        self._language = getattr(settings, "language", None) or getattr(
            settings, "default_language", None
        )
        self._timeout_s = getattr(settings, "timeout", None) or _DEFAULT_TIMEOUT_S
        # ponytail: ventana/solape (sliding-window long audio) are accepted for
        # config parity but not implemented here — each voxel turn is a single
        # short audio_chunk. Logged if set so nobody assumes it is active.
        if getattr(settings, "ventana", None) or getattr(settings, "solape", None):
            from loguru import logger

            logger.warning(
                "[parakeet] ventana/solape configured but sliding-window is not "
                "implemented in this provider; transcribing the chunk as-is"
            )

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def model(self) -> str:
        return self._model

    async def __aenter__(self) -> "ParakeetProvider":
        # Fail-open at enable(): missing binary is only surfaced at transcribe.
        return self

    async def aclose(self) -> None:
        return None

    def _argv(self, base: Path, wav: Path) -> list[str]:
        args = [
            self._bin,
            "-m", self._model,
            "--backend", "parakeet",
            "-otxt",
            "-of", str(base),
            str(wav),
        ]
        if self._backend and self._backend.lower() != "cpu":
            args.extend(["--gpu-backend", str(self._backend)])
        if self._device is not None:
            args.extend(["-dev", str(self._device)])
        if self._language:
            code = self._language.split("_")[0].split("-")[0].lower()
            if code and code != "auto":
                args.extend(["-l", code])
        return args

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        wav_bytes = _wav_bytes(audio)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(wav_bytes)
            wav_path = Path(handle.name)
        base = wav_path.with_suffix("")
        txt_path = base.with_suffix(".txt")
        try:
            await _capture(self._argv(base, wav_path), timeout_s=self._timeout_s)
            text = _read_txt(txt_path)
            if not text:
                raise ProviderError("parakeet produced no transcription text")
        finally:
            wav_path.unlink(missing_ok=True)
            txt_path.unlink(missing_ok=True)
            base.with_suffix(".json").unlink(missing_ok=True)
        return TranscriptionData(
            text=text,
            language=self._language,
            confidence=None,
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )


def _read_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _wav_bytes(audio: AudioData) -> bytes:
    match audio.format:
        case "wav":
            return audio.samples
        case "pcm_s16le":
            # crispasr expects 16 kHz mono s16le. The mic input produces this
            # natively; any other rate would need resampling (not done — ponytail).
            frame_size = audio.channels * 2
            if len(audio.samples) % frame_size != 0:
                raise UnsupportedAudioPayload(format="pcm_s16le with incomplete sample frame")
            with BytesIO() as buffer:
                with wave.open(buffer, "wb") as wav_file:
                    wav_file.setnchannels(audio.channels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(audio.sample_rate or 16_000)
                    wav_file.writeframes(audio.samples)
                return buffer.getvalue()
        case unsupported:
            raise UnsupportedAudioPayload(format=unsupported)


class ParakeetServerProvider:
    """CrispASR (parakeet) STT against an already-running ``--server`` process.

    Same contract as :class:`ParakeetProvider` (``__aenter__``/``aclose``/
    ``transcribe``) but the model is resident in the server, so per-turn cost is
    proportional to the audio, not to model load. Talks to the
    OpenAI-compatible ``POST /v1/audio/transcriptions`` endpoint (multipart), the
    same shape the whisper-server path uses.

    Fail-open: a missing/hung server surfaces as a raised error; the
    audio_processor plugin swallows it into empty output, keeping the bus alive.
    ``health()`` can be probed at startup so the operator gets a clear warning.
    """

    def __init__(
        self,
        settings: PluginSettings,
        *,
        host: str | None = None,
        port: int | None = None,
        timeout_s: float | None = None,
        path: str = _DEFAULT_SERVER_PATH,
        client: httpx.AsyncClient | None = None,
        language: str | None = None,
    ) -> None:
        self._settings = settings
        self._host = host or getattr(settings, "host", None) or _DEFAULT_HOST
        self._port = port or getattr(settings, "port", None) or _DEFAULT_PORT
        self._endpoint = f"http://{self._host}:{self._port}"
        self._path = path
        self._timeout_s = timeout_s or getattr(settings, "timeout", None) or _DEFAULT_TIMEOUT_S
        self._motor = getattr(settings, "motor", None) or _DEFAULT_MOTOR
        self._model = getattr(settings, "model", None) or "<server-resident>"
        self._language = language or getattr(settings, "language", None) or getattr(
            settings, "default_language", None
        )
        self._provided_client = client
        self._client: httpx.AsyncClient | None = None
        self._owns_client = False
        self._active = False

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def model(self) -> str:
        return self._model

    @property
    def backend(self) -> str:
        return "server"

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def is_closed(self) -> bool:
        return self._client is None or self._client.is_closed

    async def __aenter__(self) -> Self:
        if self._active:
            raise ProviderError("parakeet server already active")
        if self._provided_client is not None:
            if self._provided_client.is_closed:
                raise ProviderError("parakeet server injected client is closed")
            self._client = self._provided_client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_s), follow_redirects=True
            )
            self._owns_client = True
        self._active = True
        return self

    async def aclose(self) -> None:
        if not self._active:
            return
        client = self._client
        if client is not None and self._owns_client and not client.is_closed:
            await client.aclose()
        self._active = False

    def _client_or_raise(self) -> httpx.AsyncClient:
        client = self._client
        if not self._active or client is None or client.is_closed:
            raise ProviderError("parakeet server used outside an active lifecycle")
        return client

    async def health(self) -> bool:
        """Probe ``GET /health``. False on any non-2xx or connectivity error."""
        try:
            resp = await self._client_or_raise().get(f"{self._endpoint}/health", timeout=2.0)
            return resp.status_code < 500
        except Exception:  # noqa: BLE001 — health probe must never raise
            return False

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        data: dict[str, str] = {}
        if self._language:
            code = self._language.split("_")[0].split("-")[0].lower()
            if code and code != "auto":
                data["language"] = code
        response = await self._client_or_raise().post(
            f"{self._endpoint}{self._path}",
            data=data,
            files={"file": ("audio.wav", _wav_bytes(audio), "audio/wav")},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # Fail-open contract: upstream HTTP errors surface as ProviderError so
            # the plugin swallows them into empty output without killing the bus.
            raise ProviderError(
                f"parakeet server returned HTTP {response.status_code}"
            ) from error
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError("parakeet server returned non-JSON response") from error
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ProviderError("parakeet server produced no transcription text")
        raw_language = payload.get("language")
        return TranscriptionData(
            text=text,
            language=str(raw_language) if raw_language else self._language,
            confidence=payload.get("confidence"),
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )

    async def transcribe_parcial(
        self, pcm: bytes, *, sample_rate: int = 16_000
    ) -> str:
        """PCM crudo 16 kHz mono s16le -> texto (pasada parcial del EOT).

        Mismo contrato de fallo que ``transcribe``: ``ProviderError`` aguas arriba.
        Lo usa el mic sólo cuando ``eot_partial_hold`` está encendido; el llamador
        hace fail-open, así que acá no se atrapa nada.
        """
        audio = AudioData(
            samples=pcm,
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
        )
        transcription = await self.transcribe(audio)
        return transcription.text


class ParakeetStreamProvider:
    """Live streaming STT via the CrispASR ``--stream`` CLI path.

    Opens the binary once in ``__aenter__``: the model is loaded a single time
    and stays resident, so the per-turn cost is only the compute for the new
    block. The caller feeds raw PCM s16le 16 kHz mono in ``feed()`` chunks
    (typically ~100 ms) at real-time pace; CrispASR answers with one JSON line
    per event on stdout — ``{"type":"partial",...}`` and ``{"type":"final",...}``.

    The provider surfaces events through a single async ``on_event`` callback
    that receives a :class:`TranscriptionData` per event: ``partial=True`` for
    partial updates, ``partial=False`` for the closed ``final``. Non-JSON stdout
    lines (init chatter) are logged and ignored; the binary prints them on
    stderr, which is drained in a background task so a chatty init never blocks
    the child.

    Fail-open: if the child dies mid-stream the next ``feed()`` restarts it
    (bounded by ``stream_max_restarts``). When the retry limit is exhausted the
    provider degrades to no-streaming (drops PCM chunks with a log). It never
    raises out into the bus — the audio_processor plugin keeps running either
    way.
    """

    def __init__(self, settings: PluginSettings) -> None:
        self._settings = settings
        self._bin = getattr(settings, "bin", None) or _DEFAULT_BIN
        motor = getattr(settings, "motor", None) or _DEFAULT_MOTOR
        self._motor = motor if motor in _DEFAULT_MODEL_BY_MOTOR else _DEFAULT_MOTOR
        self._model = getattr(settings, "model", None) or _DEFAULT_MODEL_BY_MOTOR[self._motor]
        gpu_backend = getattr(settings, "gpu_backend", None) or getattr(settings, "backend", None)
        self._backend = gpu_backend if gpu_backend in _GPU_BACKENDS else "vulkan"
        self._device = getattr(settings, "device", None)
        self._language = getattr(settings, "language", None) or getattr(
            settings, "default_language", None
        )
        self._step_ms = int(getattr(settings, "stream_step_ms", None) or _DEFAULT_STREAM_STEP_MS)
        self._silence_ms = int(
            getattr(settings, "stream_final_on_silence_ms", None) or _DEFAULT_STREAM_SILENCE_MS
        )
        self._max_restarts = int(
            getattr(settings, "stream_max_restarts", None) or _DEFAULT_MAX_RESTARTS
        )
        self._final_wait_s = float(
            getattr(settings, "stream_final_wait_s", None) or _DEFAULT_FINAL_WAIT_S
        )

        # Async callback invoked with a TranscriptionData per partial/final event.
        self.on_event: Callable[[TranscriptionData], Awaitable[None]] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._spawn_lock = asyncio.Lock()
        self._final_seen = asyncio.Event()
        self._restart_count = 0
        self._degraded = False
        self._closed = True  # not open until __aenter__

    @property
    def motor(self) -> str:
        return self._motor

    @property
    def model(self) -> str:
        return self._model

    @property
    def backend(self) -> str:
        return "stream"

    @property
    def stream_step_ms(self) -> int:
        return self._step_ms

    @property
    def stream_final_on_silence_ms(self) -> int:
        return self._silence_ms

    async def __aenter__(self) -> "ParakeetStreamProvider":
        self._closed = False
        try:
            await self._spawn()
        except Exception as error:  # noqa: BROAD_EXCEPT_OK — fail-open at enable()
            # A missing binary can't be loaded now; degrade to no-streaming
            # instead of failing `enable()` and taking the plugin down with it.
            logger.error(
                "[parakeet-stream] failed to spawn at enable: {} (degraded to no-streaming)", error
            )
            self._degraded = True
            self._proc = None
        return self

    def _argv(self) -> list[str]:
        args = [
            self._bin,
            "-m", self._model,
            "--backend", "parakeet",
            "--stream",
            "--stream-json",
            "--stream-step", str(self._step_ms),
            "--stream-final-on-silence-ms", str(self._silence_ms),
        ]
        if self._backend and str(self._backend).lower() != "cpu":
            args.extend(["--gpu-backend", str(self._backend)])
        if self._device is not None:
            args.extend(["-dev", str(self._device)])
        args.append("-np")
        return args

    async def _spawn(self) -> None:
        argv = self._argv()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as error:
            raise ProviderError(f"parakeet stream binary launch failed: {self._bin}") from error
        self._proc = proc
        self._reader_task = asyncio.create_task(
            self._run_reader(proc), name="kateto-parakeet-stream-reader"
        )
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(proc), name="kateto-parakeet-stream-stderr"
        )
        logger.info(
            "[parakeet-stream] process up pid={} step={}ms silence={}ms",
            proc.pid, self._step_ms, self._silence_ms,
        )
    async def _maybe_restart(self) -> None:
        async with self._spawn_lock:
            # Re-check while holding the lock: another feed may already have
            # restarted the process in between.
            if self._proc is not None and self._proc.returncode is None:
                return
            if self._degraded or self._closed:
                return
            if self._restart_count >= self._max_restarts:
                logger.error(
                    "[parakeet-stream] restart limit ({}) reached; degrading to no-streaming",
                    self._max_restarts,
                )
                self._degraded = True
                self._proc = None
                return
            self._restart_count += 1
            logger.warning(
                "[parakeet-stream] process died; restarting (attempt {}/{})",
                self._restart_count, self._max_restarts,
            )
            try:
                await self._spawn()
            except Exception as error:  # noqa: BROAD_EXCEPT_OK
                logger.error("[parakeet-stream] restart failed: {}", error)
                self._proc = None

    async def feed(self, samples: bytes) -> None:
        """Feed a raw PCM chunk to the streaming process (non-blocking)."""
        if self._closed or self._degraded:
            return
        proc = self._proc
        if proc is None or proc.returncode is not None:
            await self._maybe_restart()
            proc = self._proc
            if proc is None:
                return
        stdin = proc.stdin
        if stdin is None or stdin.is_closing():
            await self._maybe_restart()
            proc = self._proc
            if proc is None or proc.stdin is None:
                return
            stdin = proc.stdin
        try:
            stdin.write(samples)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError, ProcessLookupError) as error:
            # The child died while we were writing (its read end closed on exit);
            # a later feed() will restart it. The bus never sees this as an error.
            logger.warning(
                "[parakeet-stream] pipe closed while feeding ({}); dropping chunk", error
            )
            self._proc = None
            await self._maybe_restart()

    async def _run_reader(self, proc: asyncio.subprocess.Process) -> None:
        try:
            while True:
                assert proc.stdout is not None
                line = await proc.stdout.readline()
                if not line:
                    break
                data = self._parse_line(line)
                if data is not None:
                    try:
                        await self._emit(data)
                    except Exception as error:  # noqa: BROAD_EXCEPT_OK
                        logger.error("[parakeet-stream] event dispatch failed: {}", error)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BROAD_EXCEPT_OK
            logger.error("[parakeet-stream] stdout reader failed: {}", error)
        finally:
            if proc is self._proc:
                self._proc = None
            logger.debug("[parakeet-stream] stdout closed (pid={})", proc.pid)
    def _parse_line(self, line: bytes) -> TranscriptionData | None:
        text = line.decode(errors="replace").strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            # Init chatter belongs on stderr (which this provider drains), but be
            # tolerant: anything that isn't a valid JSON event line is logged.
            logger.warning("[parakeet-stream] ignoring non-JSON stdout line: {!r}", text[:200])
            return None
        if not isinstance(obj, dict):
            logger.warning("[parakeet-stream] ignoring non-object JSON line: {!r}", text[:200])
            return None
        event_type = obj.get("type")
        raw_text = str(obj.get("text") or "").strip()
        if not raw_text:
            return None
        if event_type == "partial":
            return TranscriptionData(text=raw_text, language=self._language, partial=True)
        if event_type == "final":
            self._final_seen.set()
            self._restart_count = 0  # a healthy utterance completed: reset the budget
            return TranscriptionData(text=raw_text, language=self._language, partial=False)
        logger.debug("[parakeet-stream] ignoring unknown event type: {!r}", event_type)
        return None

    async def _emit(self, data: TranscriptionData) -> None:
        callback = self.on_event
        if callback is None:
            return
        await callback(data)

    async def _drain_stderr(self, proc: asyncio.subprocess.Process) -> None:
        try:
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    logger.debug("[parakeet-stream] stderr: {}", text[:300])
        except (asyncio.CancelledError, Exception):  # noqa: BROAD_EXCEPT_OK
            return

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is not None and proc.returncode is None and proc.stdin is not None:
            # Close stdin so the child sees EOF and emits its final `final` line,
            # then wait (bounded) for it before tearing the process down.
            self._final_seen = asyncio.Event()
            try:
                proc.stdin.close()
            except Exception:  # noqa: BROAD_EXCEPT_OK
                pass
            try:
                await asyncio.wait_for(
                    asyncio.gather(self._final_seen.wait(), proc.wait()),
                    timeout=self._final_wait_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[parakeet-stream] no final within {}s; killing pid={}",
                    self._final_wait_s, proc.pid,
                )
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
            finally:
                if proc.returncode is None:
                    # A `final` arrived but the child hadn't exited yet; give it a
                    # moment to flush/exit, then make sure it is gone.
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        await proc.wait()
        # Cancel reader/stderr tasks and drop the process reference for good.
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        self._proc = None
        self._reader_task = None
        self._stderr_task = None
        self._degraded = True
def create_parakeet_provider(
    settings: PluginSettings,
) -> ParakeetProvider | ParakeetServerProvider | ParakeetStreamProvider:
    """Select the transport backend: ``server`` (default) | ``cli`` | ``stream``.

    ``server`` talks to an externally-launched CrispASR process (model resident —
    the documented default). ``cli`` spawns the binary per invocation.
    ``stream`` opens the binary once in ``--stream --stream-json`` mode and feeds
    raw PCM over stdin (live partials + finals).
    """
    backend = getattr(settings, "backend", None) or _DEFAULT_TRANSPORT
    match str(backend).strip().lower():
        case "cli":
            return ParakeetProvider(settings)
        case "stream":
            return ParakeetStreamProvider(settings)
        case _:
            return ParakeetServerProvider(settings)