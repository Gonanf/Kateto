from __future__ import annotations

from typing import Protocol

from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin, PluginManagerProtocol


class WhisperTranscriber(Protocol):
    async def transcribe(self, audio: AudioData) -> TranscriptionData: ...


class WhisperAudioProcessor(Plugin):
    def __init__(self, *, provider: WhisperTranscriber) -> None:
        super().__init__("audio_processor_whisper", capabilities=("transcribe",))
        self._provider: WhisperTranscriber = provider

    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    async def on_audio_chunk(self, data: AudioData) -> None:
        transcription = await self._provider.transcribe(data)
        _ = await self._manager().emit("transcription", transcription, source=self.name)

    def _manager(self) -> PluginManagerProtocol:
        manager = self.manager
        if manager is None:
            msg = "audio processor must be enabled before use"
            raise RuntimeError(msg)
        return manager
