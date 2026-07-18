from __future__ import annotations

import pytest

from kateto.core import PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin
from kateto.plugins.audio_processor import WhisperAudioProcessor


class FixtureWhisper:
    def __init__(self) -> None:
        self.received: list[AudioData] = []

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        self.received.append(audio)
        return TranscriptionData(text="fixture transcription", language="en")


class _TestableWhisperProcessor(WhisperAudioProcessor):
    """Test helper that injects a fixture provider instead of the real one."""

    def __init__(self, fixture: FixtureWhisper) -> None:
        super().__init__(settings=PluginSettings())
        self._fixture = fixture

    async def enable(self) -> None:
        self._provider = self._fixture  # type: ignore[assignment]

    async def disable(self) -> None:
        self._provider = None


class TranscriptionSink(Plugin):
    def __init__(self) -> None:
        super().__init__("transcription_sink")
        self.received: list[TranscriptionData] = []

    async def on_transcription(self, data: TranscriptionData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_audio_chunk_flows_through_whisper_processor_to_transcription() -> None:
    # Given: the documented processor boundary is connected to a Whisper adapter and a sink.
    manager = PluginManager()
    whisper = FixtureWhisper()
    processor = _TestableWhisperProcessor(whisper)
    sink = TranscriptionSink()
    await manager.enable_plugin(processor)
    await manager.enable_plugin(sink)

    try:
        # When: one audio chunk enters the event bus.
        audio = AudioData(samples=b"\x01\x00", format="pcm_s16le", source="fixture")
        await manager.emit("audio_chunk", audio, source="audio_input_mic/microphone")
        await manager.wait_for_idle()

        # Then: the adapter sees the exact chunk and the processor emits one typed transcription.
        assert whisper.received == [audio]
        assert sink.received == [TranscriptionData(text="fixture transcription", language="en")]
        assert [(event.name, event.source) for event in manager.get_events()] == [
            ("audio_chunk", "audio_input_mic/microphone"),
            ("transcription", "audio_processor_whisper"),
        ]
    finally:
        await manager.close()
