from __future__ import annotations

import json
from asyncio import CancelledError
from typing import Final, override

import httpx

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin
from kateto.providers.whisper import _wav_bytes

from loguru import logger

log = logger

PARAKEET_TRANSCRIPTIONS_PATH: Final = "/v1/audio/transcriptions"
DEFAULT_PARAKEET_ENDPOINT: Final = "http://127.0.0.1:8098"
DEFAULT_PARAKEET_MODEL: Final = "parakeet"
DEFAULT_PARAKEET_TIMEOUT_S: Final = 15.0


class ParakeetAudioProcessor(Plugin):
    """ASR HTTP contra crispasr (Parakeet Redux), hermano de WhisperAudioProcessor."""

    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("audio_processor_parakeet", capabilities=("transcribe",))
        self._settings: PluginSettings = settings
        self._client: httpx.AsyncClient | None = None

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    @override
    async def enable(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient()

    @override
    async def disable(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()

    async def on_audio_chunk(self, data: AudioData) -> None:
        client = self._client
        if client is None:
            return
        try:
            endpoint = (getattr(self._settings, "endpoint", None) or DEFAULT_PARAKEET_ENDPOINT).rstrip("/")
            model = getattr(self._settings, "model", None) or DEFAULT_PARAKEET_MODEL
            form: dict[str, str] = {
                "model": model,
                "response_format": "json",
                "temperature": "0.0",
            }
            lang = getattr(self._settings, "language", None) or getattr(self._settings, "default_language", None)
            if lang:
                code = lang.split("_")[0].split("-")[0].lower()
                if code != "auto":
                    form["language"] = code
            timeout_s = getattr(self._settings, "timeout_s", None)
            timeout = DEFAULT_PARAKEET_TIMEOUT_S if timeout_s is None else timeout_s
            response = await client.post(
                f"{endpoint}{PARAKEET_TRANSCRIPTIONS_PATH}",
                data=form,
                files={"file": ("audio.wav", _wav_bytes(data), "audio/wav")},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = json.loads(response.content)
            raw = payload.get("text") if isinstance(payload, dict) else None
            text = raw.strip() if isinstance(raw, str) else ""
            if not text:
                log.debug("[parakeet] No speech detected in audio chunk")
                return
            transcription = TranscriptionData(
                text=text,
                duration_ms=data.duration_ms or None,
                voice=data.voice,
            )
            await self.required_manager.emit("transcription", transcription, source=self.name)
        except CancelledError:
            raise
        except Exception as err:
            log.error("[parakeet] Transcription error: {}", err)
