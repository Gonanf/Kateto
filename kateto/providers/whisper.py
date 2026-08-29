from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Final
import wave

import httpx
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.exceptions import ProviderError

from ._http import HttpProvider, configured_endpoint
from ._local import LocalCommandProvider, _capture, _first_json, _read_whisper_json
from ._models import WhisperResponse
from .errors import MalformedUpstreamResponse, UnsupportedAudioPayload


WHISPER_INFERENCE_PATH: Final = "/inference"


class LocalWhisperProvider(LocalCommandProvider):
    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(_wav_bytes(audio))
            wav_path = Path(handle.name)
        json_path = wav_path.with_suffix(".json")
        try:
            args = ["-f", str(wav_path), "-oj"]
            lang = getattr(self._settings, "language", None) or getattr(self._settings, "default_language", None)
            if lang:
                code = lang.split("_")[0].split("-")[0].lower()
                if code != "auto":
                    args.extend(["-l", code])
            out = await _capture(self._argv(*args))
            data = _read_whisper_json([json_path]) or _first_json(out)
            if data is None or not data.get("text"):
                raise ProviderError(f"{type(self).__name__} produced no transcription text")
        finally:
            wav_path.unlink(missing_ok=True)
            json_path.unlink(missing_ok=True)
        return TranscriptionData(
            text=data["text"],
            language=data.get("language"),
            confidence=None,
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )


class WhisperProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = WHISPER_INFERENCE_PATH,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            provider_name="whisper",
            endpoint=configured_endpoint(settings, provider="whisper", endpoint=endpoint),
            client=client,
            timeout_s=timeout_s,
        )
        self._settings = settings
        self._path = path

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        data: dict[str, Any] = {"response_format": "json", "temperature": "0.0"}
        lang = getattr(self._settings, "language", None) or getattr(self._settings, "default_language", None)
        if lang:
            code = lang.split("_")[0].split("-")[0].lower()
            if code != "auto":
                data["language"] = code
        response = await self._client_or_raise().post(
            self._url(self._path),
            data=data,
            files={"file": ("audio.wav", _wav_bytes(audio), "audio/wav")},
            headers=self._request_headers,
        )
        response.raise_for_status()
        try:
            payload = WhisperResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedUpstreamResponse(provider="whisper", reason="expected transcription JSON") from error
        return TranscriptionData(
            text=payload.text,
            language=payload.language,
            confidence=payload.confidence,
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )


def _wav_bytes(audio: AudioData) -> bytes:
    match audio.format:
        case "wav":
            return audio.samples
        case "pcm_s16le":
            frame_size = audio.channels * 2
            if len(audio.samples) % frame_size != 0:
                raise UnsupportedAudioPayload(format="pcm_s16le with incomplete sample frame")
            with BytesIO() as buffer:
                with wave.open(buffer, "wb") as wav_file:
                    wav_file.setnchannels(audio.channels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(audio.sample_rate)
                    wav_file.writeframes(audio.samples)
                return buffer.getvalue()
        case unsupported:
            raise UnsupportedAudioPayload(format=unsupported)


class PyWhisperCppProvider:
    """In-process whisper.cpp speech-to-text provider using pywhispercpp Python bindings."""

    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        model: str | None = None,
        n_threads: int = 4,
        language: str | None = None,
    ) -> None:
        self._settings = settings
        self._model_name = model or (settings.model if settings else None) or "base.en"
        self._n_threads = n_threads
        resolved_lang = (
            language
            or getattr(settings, "language", None)
            or getattr(settings, "default_language", None)
        )
        if resolved_lang:
            resolved_lang = resolved_lang.split("_")[0].split("-")[0].lower()
            if resolved_lang == "auto":
                resolved_lang = None
        self._language = resolved_lang
        self._model: Any = None

    async def __aenter__(self) -> PyWhisperCppProvider:
        await self._ensure_initialized()
        return self

    async def aclose(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            import gc
            gc.collect()

    async def _ensure_initialized(self) -> None:
        if self._model is not None:
            return
        try:
            from pywhispercpp.model import Model
        except ImportError as err:
            raise ProviderError(
                "pywhispercpp is not installed. Install the optional feature with `uv pip install 'kateto[whispercpp]'` "
                "or `uv tool install 'kateto[whispercpp]'` (prebuilt binary wheel, no compilation needed)."
            ) from err

        def _load() -> Any:
            return Model(self._model_name, n_threads=self._n_threads)

        self._model = await asyncio.to_thread(_load)

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        await self._ensure_initialized()
        wav_data = _wav_bytes(audio)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            handle.write(wav_data)
            wav_path = Path(handle.name)

        try:
            def _run() -> str:
                kwargs: dict[str, Any] = {}
                if self._language:
                    kwargs["language"] = self._language
                segments = self._model.transcribe(str(wav_path), **kwargs)
                return " ".join(seg.text for seg in segments).strip()

            text = await asyncio.to_thread(_run)
        finally:
            wav_path.unlink(missing_ok=True)

        return TranscriptionData(
            text=text,
            language=self._language,
            confidence=None,
            duration_ms=audio.duration_ms if audio.duration_ms > 0 else None,
        )


class WhisperServerProcessProvider:
    """Instantiates a whisper-server subprocess and proxies HTTP transcription requests to it."""

    def __init__(
        self,
        settings: PluginSettings,
        *,
        server_binary: str | None = None,
        model_path: str | None = None,
        port: int = 8090,
        host: str = "127.0.0.1",
        threads: int = 4,
    ) -> None:
        self._settings = settings
        binary = server_binary or getattr(settings, "command", None) or "whisper-server"
        if shutil.which(binary) is None:
            for candidate in (
                Path.home() / "proyectos" / "whisper.cpp" / "build" / "bin" / "whisper-server",
                Path.home() / ".local" / "bin" / "whisper-server",
            ):
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    binary = str(candidate)
                    break
        self._binary = binary
        self._model_path = model_path or settings.model or ""
        self._port = port
        self._host = host
        self._threads = threads
        self._process: asyncio.subprocess.Process | None = None
        self._http_provider: WhisperProvider | None = None

    async def __aenter__(self) -> WhisperServerProcessProvider:
        await self.start()
        return self

    async def aclose(self) -> None:
        await self.stop()

    async def start(self) -> None:
        endpoint = f"http://{self._host}:{self._port}"
        # Check if already running / reachable
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(endpoint, timeout=1.0)
                if resp.status_code < 500:
                    self._http_provider = WhisperProvider(self._settings, endpoint=endpoint)
                    await self._http_provider.__aenter__()
                    return
            except Exception:
                pass

        cmd = [
            self._binary,
            "--host", self._host,
            "--port", str(self._port),
            "--threads", str(self._threads),
        ]
        if self._model_path:
            cmd.extend(["--model", self._model_path])
        device = getattr(self._settings, "device", None)
        if device is not None:
            cmd.extend(["--device", str(device)])
        elif shutil.which("vulkaninfo") is not None:
            # Default to Vulkan GPU device 1 (e.g. discrete AMD) or 0
            cmd.extend(["--device", "1"])
        lang = getattr(self._settings, "language", None) or getattr(self._settings, "default_language", None)
        if lang:
            code = lang.split("_")[0].split("-")[0].lower()
            if code != "auto":
                cmd.extend(["-l", code])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as err:
            raise ProviderError(
                f"whisper-server binary '{self._binary}' not found. "
                "Compile it with `kateto compile whisper` or configure an external endpoint."
            ) from err

        async with httpx.AsyncClient() as client:
            for _ in range(30):
                await asyncio.sleep(0.5)
                if self._process.returncode is not None:
                    raise ProviderError(f"whisper-server exited prematurely with code {self._process.returncode}")
                try:
                    resp = await client.get(endpoint, timeout=1.0)
                    if resp.status_code < 500:
                        break
                except Exception:
                    continue
            else:
                await self.stop()
                raise ProviderError(f"Timed out waiting for whisper-server on {endpoint}")

        self._http_provider = WhisperProvider(self._settings, endpoint=endpoint)
        await self._http_provider.__aenter__()

    async def stop(self) -> None:
        if self._http_provider is not None:
            await self._http_provider.aclose()
            self._http_provider = None
        if self._process is not None:
            try:
                self._process.terminate()
                await self._process.wait()
            except Exception:
                pass
            self._process = None

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        if self._http_provider is None:
            raise ProviderError("whisper server provider is not running")
        return await self._http_provider.transcribe(audio)

