from unittest.mock import AsyncMock, MagicMock

import pytest

from kateto.core.event import ProcessTranscriptionData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.audio_processor.process_audio_whisper_plugin import ProcessAudioWhisperPlugin


class TranscriptionListenerPlugin(Plugin):
    def __init__(self):
        super().__init__(name="transcription_listener")
        self.received = []

    async def on_process_transcription(self, data: ProcessTranscriptionData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_process_audio_whisper_plugin_transcribes_and_emits():
    manager = PluginManager()

    mock_whisper = MagicMock()
    mock_whisper.transcribe = AsyncMock(return_value="Meeting status updated")

    plugin = ProcessAudioWhisperPlugin(
        source_pid=1234,
        dept="fun",
        whisper_transcriber=mock_whisper,
    )
    listener = TranscriptionListenerPlugin()

    await manager.enable_plugin(listener)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Trigger process audio capture manually
    await plugin.on_process_audio_capture_trigger()
    await manager.wait_for_idle()

    assert len(listener.received) == 1
    trans_data = listener.received[0]
    assert isinstance(trans_data, ProcessTranscriptionData)
    assert trans_data.text == "Meeting status updated"
    assert trans_data.source_pid == 1234
    assert trans_data.dept == "fun"

    await manager.disable_plugin(plugin.name)
    await manager.disable_plugin(listener.name)
