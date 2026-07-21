from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import (
    GenerateData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VoiceRequestData,
    WorkflowPhaseStartData,
)
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


def _reference(config_dir: Path) -> None:
    path = config_dir / "voices" / "jane" / "reference.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFFfixtureWAVE")


@pytest.mark.asyncio
async def test_voice_provider_request_includes_bounded_event_history_once(tmp_path: Path) -> None:
    # Given: a voice that has received a transcription before its generation trigger.
    _reference(tmp_path)
    provider = RecordingProvider()
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: the same event-derived request is generated after context accumulation.
        await manager.emit("transcription", TranscriptionData(text="remember this context"), source="fixture")
        await manager.wait_for_idle()
        await manager.emit("generate", GenerateData(prompt="remember this context"), source="fixture")
        await manager.wait_for_idle()

        # Then: the provider sees retained context exactly once and the history is bounded.
        contents = [message.content for message in provider.requests[0].messages]
        assert contents.count("remember this context") == 1
        assert len(voice.message_history) <= 32
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_voice_provider_history_retains_received_events_and_own_output_once(tmp_path: Path) -> None:
    # Given: a voice with a bounded provider and event-shaped context from the event bus.
    _reference(tmp_path)
    provider = RecordingProvider()
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: received events and the voice's own generated event are followed by another request.
        await manager.emit("transcription", TranscriptionData(text="transcribed"), source="fixture")
        await manager.emit("text_chunk", TextChunk(text="chat message", sequence=0), source="fixture")
        await manager.emit(
            "voice_request",
            VoiceRequestData(voice="jane", prompt="current prompt"),
            source="fixture",
            target="jane",
        )
        await manager.emit(
            "tool_call",
            ToolCallData(
                tool_name="read_file",
                arguments={"path": "notes.md"},
                correlation_id="call-1",
                voice="jane",
            ),
            source="fixture",
        )
        await manager.emit(
            "tool_result",
            ToolResultData(
                tool_name="read_file",
                result="tool output" + (" oversized" * 1_000),
                correlation_id="call-1",
                voice="jane",
            ),
            source="fixture",
        )
        await manager.emit(
            "workflow_phase_start",
            WorkflowPhaseStartData(
                workflow="brief",
                phase_id="ask",
                voice="jane",
                instructions=["ask the team"],
            ),
            source="fixture",
        )
        await manager.wait_for_idle()
        await manager.emit("generate", GenerateData(prompt="current prompt"), source="fixture")
        await manager.wait_for_idle()
        await manager.emit("generate", GenerateData(prompt="follow-up"), source="fixture")
        await manager.wait_for_idle()

        # Then: semantic history is bounded, the current prompt appears once, and own output is retained once.
        contents = [message.content for message in provider.requests[1].messages]
        assert sum("transcribed" in content for content in contents) == 1
        assert sum("chat message" in content for content in contents) == 1
        assert sum("current prompt" in content for content in contents) == 1
        assert sum(content.startswith("tool_call read_file") for content in contents) == 1
        assert sum(content.startswith("tool_result read_file") for content in contents) == 1
        assert sum("brief" in content and "ask" in content for content in contents) == 1
        assert sum(content == "reply" for content in contents) == 1
        assert all(len(content) <= 2_048 for content in contents)
        assert len(voice.message_history) <= 32
    finally:
        await manager.close()
