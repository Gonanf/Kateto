from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import (
    GenerateData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VoiceIdleData,
    VoiceRequestData,
    VoiceStatus,
    VoiceStatusData,
    WorkflowPhaseStartData,
)
from kateto.providers.agent import (
    AgentResponse,
    OpenAIAgentProvider,
    StreamToken,
    ToolCall,
)
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole
from kateto.voices.tools import build_event_tools


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


class ToolCallingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_with_tools_stream(
        self,
        *,
        messages: list[dict[str, object]],
        tools: tuple[object, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        self.calls += 1
        if self.calls == 1:
            yield AgentResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="remember",
                        arguments={"value": "done"},
                    ),
                ),
            )
            return
        yield AgentResponse(text="The tool completed, so I can answer now.")

    async def chat_with_tools(self, *, messages: list[dict[str, object]], tools: tuple[object, ...]) -> AgentResponse:
        raise AssertionError("the streaming agent path should be used")


class RecordingToolExecutor:
    async def execute(self, name: str, arguments: dict[str, object]) -> str:
        assert name == "remember"
        return "remembered"


class FailingAfterToolProvider(ToolCallingProvider):
    async def chat_with_tools_stream(
        self,
        *,
        messages: list[dict[str, object]],
        tools: tuple[object, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        self.calls += 1
        if self.calls == 1:
            yield AgentResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="remember",
                        arguments={"value": "done"},
                    ),
                ),
            )
            return
        raise RuntimeError("upstream disconnected after tool call")


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
async def test_agent_emits_final_response_after_streamed_tool_call(tmp_path: Path) -> None:
    # Given: an agent provider that returns the post-tool answer as an AgentResponse.
    _reference(tmp_path)
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=RecordingProvider(),
        settings=VoiceSettings(),
    )
    agent_provider = ToolCallingProvider()
    voice.setup_agent(
        agent_provider=cast(OpenAIAgentProvider, cast(object, agent_provider)),
        tool_executor=RecordingToolExecutor(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: the model calls a tool and then returns its final assistant response.
        await manager.emit("generate", GenerateData(prompt="use the tool"), source="fixture")
        await manager.wait_for_idle()

        # Then: the final response is delivered to the event bus instead of being dropped.
        chunks = [
            event.data.text
            for event in manager.get_events()
            if event.name == "text_chunk" and isinstance(event.data, TextChunk)
        ]
        assert chunks == ["The tool completed, so I can answer now."]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_agent_returns_to_idle_when_provider_fails_after_tool_call(tmp_path: Path) -> None:
    # Given: an agent provider that fails while requesting the post-tool answer.
    _reference(tmp_path)
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=RecordingProvider(),
        settings=VoiceSettings(),
    )
    voice.setup_agent(
        agent_provider=cast(OpenAIAgentProvider, cast(object, FailingAfterToolProvider())),
        tool_executor=RecordingToolExecutor(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: the provider fails after the tool result has been appended.
        await manager.emit("generate", GenerateData(prompt="use the tool"), source="fixture")
        await manager.wait_for_idle()

        # Then: the bus reports the failure but the voice is not left thinking forever.
        statuses = [
            event.data.status
            for event in manager.get_events()
            if event.name == "voice_status" and isinstance(event.data, VoiceStatusData)
        ]
        assert statuses[-1] is VoiceStatus.IDLE
        assert any(
            event.name == "voice_idle" and isinstance(event.data, VoiceIdleData)
            for event in manager.get_events()
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_voice_provider_request_enforces_project_language(tmp_path: Path) -> None:
    # Given: a voice configured for the project's Spanish response language.
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
        response_language="es",
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: the user asks in another language.
        await manager.emit("generate", GenerateData(prompt="Please summarize this"), source="fixture")
        await manager.wait_for_idle()

        # Then: every provider path receives the project-language instruction.
        system_message = provider.requests[0].messages[0].content
        assert "project's configured language: es" in system_message
        assert "overrides the language of the user input" in system_message
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_workflow_request_adds_internal_engine_system_message(tmp_path: Path) -> None:
    _reference(tmp_path)
    workflow = tmp_path / "voices" / "jane" / "workflows" / "project-initiation" / "workflow.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name = 'project-initiation'\n"
        "description = 'Start a project'\n"
        "voice = 'Jane'\n"
        "phases = [{'id': 'stakeholders', 'name': 'Stakeholders', "
        "'instructions': ['Identify stakeholders'], "
        "'deliverables': ['stakeholder-registry.md'], "
        "'checkpoints': ['All stakeholders documented']}]\n",
        encoding="utf-8",
    )
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
        await manager.emit(
            "voice_request",
            VoiceRequestData(
                voice="jane",
                prompt="Tell me who the stakeholders are",
                workflow="project-initiation",
                phase_id="stakeholders",
            ),
            source="workflow_engine",
            target="jane",
        )
        await manager.wait_for_idle()

        system_message = provider.requests[0].messages[0].content
        assert "WORKFLOW ENGINE SYSTEM MESSAGE" in system_message
        assert "Ask the user the questions required by the phase" in system_message
        assert "use the available tools" in system_message
        assert "project-initiation" in system_message
        assert "stakeholders" in system_message
        assert "stakeholder-registry.md" in system_message
        assert "All stakeholders documented" in system_message
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_workflow_completion_tool_describes_array_fields_for_the_model(tmp_path: Path) -> None:
    _reference(tmp_path)
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=RecordingProvider(),
        settings=VoiceSettings(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        completion = next(
            tool for tool in build_event_tools(manager)
            if tool["function"]["name"] == "workflow_phase_complete"
        )
        schema = str(completion["function"].get("parameters"))
        assert "'deliverables': {'type': 'array'" in schema
        assert "'checkpoint_results': {'type': 'array'" in schema
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_voice_provider_request_lists_available_workflows(tmp_path: Path) -> None:
    # Given: a Jane voice with a project-initiation workflow in its catalog.
    _reference(tmp_path)
    workflow = tmp_path / "voices" / "jane" / "workflows" / "project-initiation" / "workflow.py"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name = 'project-initiation'\n"
        "description = 'Start a new project'\n"
        "voice = 'Jane'\n"
        "phases = [{'id': 'start', 'name': 'start', 'instructions': ['start']}]\n",
        encoding="utf-8",
    )
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
        # When: Jane receives a request about a new project.
        await manager.emit("generate", GenerateData(prompt="I started a new project"), source="fixture")
        await manager.wait_for_idle()

        # Then: her provider context names the workflow and its event-driven start mechanism.
        system_message = provider.requests[0].messages[0].content
        assert "project-initiation" in system_message
        assert "workflow_run" in system_message
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
