from __future__ import annotations

import asyncio
import base64
import json
import pytest

from kateto.core.event import (
    AudioData,
    AudioOutput,
    InterruptData,
    TextChunk,
    ToolCallData,
    TranscriptionData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.audio_processor.omnimodal_connector import (
    OmnimodalConnectorPlugin,
    SimulatedRealtimeSession,
)


class EventSinkPlugin(Plugin):
    """Observer plugin to record emitted events."""

    def __init__(self) -> None:
        super().__init__("event_sink")
        self.audio_outputs: list[AudioOutput] = []
        self.text_chunks: list[TextChunk] = []
        self.transcriptions: list[TranscriptionData] = []
        self.tool_calls: list[ToolCallData] = []

    async def on_audio_output(self, data: AudioOutput) -> None:
        self.audio_outputs.append(data)

    async def on_text_chunk(self, data: TextChunk) -> None:
        self.text_chunks.append(data)

    async def on_transcription(self, data: TranscriptionData) -> None:
        self.transcriptions.append(data)

    async def on_tool_call(self, data: ToolCallData) -> None:
        self.tool_calls.append(data)


@pytest.mark.asyncio
async def test_omnimodal_connector_initialization() -> None:
    # Given:
    plugin = OmnimodalConnectorPlugin(
        name="omnimodal_test",
        endpoint_url="ws://localhost:9090/v1/realtime",
        model_name="openbmb/MiniCPM-o-4_5-gguf",
        voice_id="jane",
    )
    manager = PluginManager()

    # When:
    await manager.enable_plugin(plugin)

    # Then:
    assert plugin.enabled is True
    assert plugin._is_active is True

    await manager.disable_plugin(plugin.name)
    assert plugin.enabled is False
    assert plugin._is_active is False


@pytest.mark.asyncio
async def test_omnimodal_connector_streams_audio_data() -> None:
    # Given:
    session = SimulatedRealtimeSession(voice_id="jane")
    plugin = OmnimodalConnectorPlugin(name="omnimodal_stream", session=session)
    manager = PluginManager()
    await manager.enable_plugin(plugin)

    # When:
    audio_event = AudioData(samples=b"\x01\x02\x03\x04", sample_rate=16000)
    await manager.emit("audio_data", audio_event, source="audio_input")
    await asyncio.sleep(0.05)

    # Then:
    assert not session.audio_queue.empty()
    chunk = await session.audio_queue.get()
    assert chunk == b"\x01\x02\x03\x04"

    await manager.disable_plugin(plugin.name)


@pytest.mark.asyncio
async def test_omnimodal_connector_handles_server_events() -> None:
    # Given:
    plugin = OmnimodalConnectorPlugin(name="omnimodal_events")
    sink = EventSinkPlugin()
    manager = PluginManager()
    await manager.enable_plugin(plugin)
    await manager.enable_plugin(sink)

    # When 1: Handle audio delta (PCM output)
    pcm_raw = b"\x05\x06\x07\x08"
    pcm_b64 = base64.b64encode(pcm_raw).decode("utf-8")
    await plugin.handle_server_event(
        {
            "type": "response.audio.delta",
            "delta": pcm_b64,
            "sample_rate": 24000,
            "final": False,
        }
    )

    # When 2: Handle text delta
    await plugin.handle_server_event(
        {
            "type": "response.text.delta",
            "delta": "Hello Kateto!",
            "final": True,
        }
    )

    # When 3: Handle user input transcription
    await plugin.handle_server_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Analyze current backlog",
            "confidence": 0.98,
        }
    )

    # When 4: Handle tool call
    await plugin.handle_server_event(
        {
            "type": "response.function_call_arguments.done",
            "name": "get_backlog_summary",
            "call_id": "call_123",
            "arguments": json.dumps({"status": "In Sprint"}),
        }
    )

    await asyncio.sleep(0.05)

    # Then:
    assert len(sink.audio_outputs) == 1
    assert sink.audio_outputs[0].samples == pcm_raw
    assert sink.audio_outputs[0].sample_rate == 24000
    assert sink.audio_outputs[0].voice_id == "jane"

    assert len(sink.text_chunks) == 1
    assert sink.text_chunks[0].text == "Hello Kateto!"

    assert len(sink.transcriptions) == 1
    assert sink.transcriptions[0].text == "Analyze current backlog"

    assert len(sink.tool_calls) == 1
    assert sink.tool_calls[0].tool_name == "get_backlog_summary"
    assert sink.tool_calls[0].arguments == {"status": "In Sprint"}

    await manager.disable_plugin(plugin.name)
    await manager.disable_plugin(sink.name)


@pytest.mark.asyncio
async def test_omnimodal_connector_handles_interrupt() -> None:
    # Given:
    session = SimulatedRealtimeSession(voice_id="jane")
    plugin = OmnimodalConnectorPlugin(name="omnimodal_interrupt", session=session)
    manager = PluginManager()
    await manager.enable_plugin(plugin)

    await session.send_audio_chunk(b"\x00" * 100)
    assert not session.audio_queue.empty()

    # When:
    await manager.emit("interrupt", InterruptData(reason="user_speaking"), source="audio_input")
    await asyncio.sleep(0.05)

    # Then:
    assert session.is_interrupted is True
    assert session.audio_queue.empty()

    await manager.disable_plugin(plugin.name)
