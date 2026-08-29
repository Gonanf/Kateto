from __future__ import annotations

from typing import TYPE_CHECKING, override

from loguru import logger

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin

log = logger

if TYPE_CHECKING:
    from kateto.providers import WhisperProvider


class WhisperAudioProcessor(Plugin):
    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("audio_processor_whisper", capabilities=("transcribe",))
        self._settings: PluginSettings = settings
        self._provider: WhisperProvider | None = None

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    @override
    async def enable(self) -> None:
        backend = getattr(self._settings, "backend", None)
        if backend == "pywhispercpp":
            from kateto.providers import PyWhisperCppProvider

            provider = PyWhisperCppProvider(self._settings)
        elif backend == "server":
            from kateto.providers import WhisperServerProcessProvider

            provider = WhisperServerProcessProvider(self._settings)
        elif self._settings.command or backend == "command":
            from kateto.providers import LocalWhisperProvider

            provider = LocalWhisperProvider(self._settings)
        elif self._settings.endpoint or backend == "http":
            from kateto.providers import WhisperProvider

            provider = WhisperProvider(self._settings)
        else:
            try:
                import pywhispercpp  # noqa: F401
                from kateto.providers import PyWhisperCppProvider

                provider = PyWhisperCppProvider(self._settings)
            except ImportError:
                from kateto.providers import WhisperProvider

                provider = WhisperProvider(self._settings)
        await provider.__aenter__()
        self._provider = provider

    @override
    async def disable(self) -> None:
        if self._provider is not None:
            await self._provider.aclose()
            self._provider = None

    async def on_audio_chunk(self, data: AudioData) -> None:
        provider = self._provider
        if provider is None:
            msg = "whisper processor must be enabled before use"
            raise RuntimeError(msg)
        try:
            transcription = await provider.transcribe(data)
            if not transcription.text or not transcription.text.strip():
                log.debug("[whisper] No speech detected in audio chunk")
                return
            log.info("[whisper] Transcribed: {!r}", transcription.text)
            _ = await self.required_manager.emit("transcription", transcription, source=self.name)
        except Exception as err:
            log.error("[whisper] Transcription error: {}", err)
