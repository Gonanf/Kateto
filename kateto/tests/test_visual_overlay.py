import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from kateto.core.event import AudioOutput, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin


@pytest.mark.asyncio
async def test_visual_overlay_compute_rms_and_broadcast():
    plugin = VisualOverlayPlugin()
    manager = PluginManager()

    # Generate 100 16-bit PCM samples
    samples = struct.pack("<100h", *[5000] * 100)
    rms = plugin.compute_rms(samples)
    assert 0.0 < rms < 1.0

    # Mock websocket connection
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()

    await plugin.register_websocket(mock_ws)

    # Test subtitle chunk event
    chunk = TextChunk(text="Hello overlay", sequence=1, voice_id="jane")
    await plugin.on_text_chunk(chunk)

    mock_ws.send_json.assert_called_once_with({"type": "subtitle", "text": "Hello overlay", "voice_id": "jane"})

    # Test audio output event
    audio = AudioOutput(samples=samples, sample_rate=16000, channels=1, voice_id="jane")
    await plugin.on_audio_output(audio)

    assert mock_ws.send_json.call_count == 2
    second_call_args = mock_ws.send_json.call_args_list[1][0][0]
    assert second_call_args["type"] == "viseme"
    assert second_call_args["voice_id"] == "jane"
    assert second_call_args["rms"] > 0
