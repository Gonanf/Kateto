from __future__ import annotations

from typing import TYPE_CHECKING, override

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager

if TYPE_CHECKING:
    from kateto.providers import WhisperProvider


class WhisperAudioProcessor(Plugin):
    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("audio_processor_whisper", capabilities=("transcribe",))
        self._settings: PluginSettings = settings
        self._provider: WhisperProvider | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    @override
    async def enable(self) -> None:
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
        transcription = await provider.transcribe(data)
        _ = await self._manager().emit("transcription", transcription, source=self.name)

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = "audio processor must be enabled before use"
            raise RuntimeError(msg)
        return manager
