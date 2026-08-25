"""Workflow e2e: a workflow running end-to-end on the real bus.

No fixtures at the orchestration level: the real WorkflowEngine drives phases,
the voice answers with real tool calls (write_file, then
workflow_phase_complete with checkpoint results), and checkpoints gate phase
advancement. Only the LLM provider itself is a deterministic stub — that seam
is exactly what live mode swaps for llama.cpp/OpenAI.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import PluginSettings, VoiceSettings
from kateto.core.event import (
    TextChunk,
    ToolCallData,
    ToolResultData,
    WorkflowCompletedData,
    WorkflowPhaseCompleteData,
    WorkflowPhaseStartData,
    WorkflowRunData,
    WorkflowStartedData,
)
from kateto.core.workflow_engine import WorkflowEngine
from kateto.providers.agent import AgentResponse, StreamToken, ToolCall
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole


def _write_workflow(config_dir: Path) -> None:
    path = config_dir / "voices" / "doktor" / "workflows" / "risk-review" / "workflow.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name = 'risk-review'\n"
        "description = 'Produce a risk register file.'\n"
        "voice = 'doktor'\n"
        "auto_advance = True\n"
        "can_stop = True\n"
        "phases = [{\n"
        "  'id': 'draft',\n"
        "  'name': 'Draft',\n"
        "  'instructions': ['Write risks.md with the top three project risks.'],\n"
        "  'deliverables': ['risks.md'],\n"
        "  'checkpoints': ['risks.md exists'],\n"
        "}]\n",
        encoding="utf-8",
    )


class _ToolCallingProvider:
    """Scripted provider: first turn calls write_file, second closes the phase."""

    def __init__(self) -> None:
        self.turn = 0

    async def chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: tuple,
    ) -> AgentResponse:
        # Non-streaming fallback: collapse the scripted stream into one response.
        text_parts: list[str] = []
        tool_calls: tuple[ToolCall, ...] = ()
        async for item in self.chat_with_tools_stream(messages, tools):
            match item:
                case StreamToken(text=token):
                    text_parts.append(token)
                case AgentResponse() as response:
                    tool_calls = response.tool_calls
        return AgentResponse(text="".join(text_parts), tool_calls=tool_calls)

    async def chat_with_tools_stream(
        self,
        messages: list[dict[str, object]],
        tools: tuple,
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        self.turn += 1
        names = {tool["function"]["name"] for tool in tools}
        assert {"write_file", "send_event"}.issubset(names), (
            "voice must see its built-in tools (file + event dispatch)"
        )
        if self.turn == 1:
            yield StreamToken(text="Writing the risk register.")
            yield AgentResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="write_file",
                        arguments={
                            "path": "risks.md",
                            "content": "# Risks\n\n1. scope\n2. latency\n3. staffing\n",
                        },
                    ),
                ),
            )
        elif self.turn == 2:
            yield StreamToken(text="Risks written; closing the phase.")
            yield AgentResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        id="call-2",
                        name="send_event",
                        arguments={
                            "event_name": "workflow_phase_complete",
                            "data": {
                                "workflow": "risk-review",
                                "voice": "doktor",
                                "phase_id": "draft",
                                "deliverables": ["risks.md"],
                                "checkpoint_results": [
                                    {"checkpoint": "risks.md exists", "passed": True},
                                ],
                            },
                            "target": "workflow_engine",
                        },
                    ),
                ),
            )
        else:
            # Terminal turn: a final text-only response ends the agent loop
            # instead of re-emitting send_event forever.
            yield StreamToken(text="Phase closed.")
            yield AgentResponse(text="Phase closed.", tool_calls=())



def _make_voice(config_dir: Path, provider: _ToolCallingProvider | None = None) -> VoiceAgent:
    reference = config_dir / "voices" / "doktor" / "reference.wav"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"RIFFfixtureWAVE")
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="doktor",
            display_name="Doktor",
            role=VoiceRole.DELIVERY_ADVISOR,
            system_prompt="You are Doktor.",
            relevance_terms=frozenset(),
        ),
        config_dir=config_dir,
        provider=provider or _ToolCallingProvider(),  # type: ignore[arg-type]
        settings=VoiceSettings(stream=True),
    )
    # Route generation through the agent loop so the scripted tool-calling
    # provider is exercised (plain provider.stream is unused in this mode).
    voice._agent_provider = voice._provider  # type: ignore[assignment]
    from kateto.voices.tools import BUILTIN_TOOLS, VoiceToolExecutor

    executor = VoiceToolExecutor(
        config_dir=config_dir, manager=None, voice_name="doktor"
    )
    voice.setup_agent(agent_provider=voice._provider, tool_executor=executor)  # type: ignore[arg-type]
    return voice


@pytest.mark.asyncio
async def test_workflow_runs_end_to_end_with_real_tool_calls(tmp_path: Path) -> None:
    # Given: doktor owns a one-phase workflow whose deliverable is a real file.
    _write_workflow(tmp_path)
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    await manager.enable_plugin(engine)

    voice = _make_voice(tmp_path)
    await manager.enable_plugin(voice)
    await manager.wait_for_idle(timeout=5)

    try:
        # When: the workflow starts (as the router or an HTTP caller would).
        await manager.emit(
            "workflow_run",
            WorkflowRunData(workflow="risk-review", voice="doktor"),
            source="test",
        )
        await manager.wait_for_idle(timeout=15)

        # Then: the full lifecycle ran on the bus.
        events = manager.get_events()
        started = [e for e in events if isinstance(e.data, WorkflowStartedData)]
        phases = [e for e in events if isinstance(e.data, WorkflowPhaseStartData)]
        completed = [e for e in events if isinstance(e.data, WorkflowCompletedData)]
        assert [p.data.phase_id for p in phases] == ["draft"]
        assert completed, "workflow never completed"

        # The deliverable was produced by a real write_file tool call.
        deliverable = tmp_path / "risks.md"
        assert deliverable.exists()
        assert "Risks" in deliverable.read_text(encoding="utf-8")

        # Tool calls/results round-tripped through the bus. The second call is
        # the send_event tool (the voice's channel to the workflow engine).
        calls = [e.data for e in events if isinstance(e.data, ToolCallData)]
        results = [e.data for e in events if isinstance(e.data, ToolResultData)]
        assert [c.tool_name for c in calls] == ["write_file", "send_event"]
        assert all(r.error is None for r in results)
        # The dispatched event reached the engine as workflow_phase_complete.
        phase_completes = [
            e.data for e in events if isinstance(e.data, WorkflowPhaseCompleteData)
        ]
        assert len(phase_completes) == 1
        assert phase_completes[0].phase_id == "draft"

        # Spoken output streamed phrase-by-phrase before each tool batch.
        chunks = [
            e.data.text for e in events if isinstance(e.data, TextChunk)
        ]
        assert any("risk register" in c for c in chunks)
        assert any("closing the phase" in c for c in chunks)

        # And the run is terminal.
        snapshot = engine.snapshot(workflow="risk-review", voice="doktor")
        assert snapshot is not None and snapshot.status == "completed"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_failed_checkpoint_pauses_workflow_instead_of_advancing(tmp_path: Path) -> None:
    # Given: the voice honestly reports its checkpoint as FAILED (the file was
    # never written). The engine must pause instead of advancing to completion.
    _write_workflow(tmp_path)
    manager = PluginManager()
    await manager.enable_plugin(WorkflowEngine(config_dir=tmp_path))

    class _FailingProvider(_ToolCallingProvider):
        async def chat_with_tools_stream(self, messages, tools):  # noqa: ANN001
            self.turn += 1
            if self.turn == 1:
                yield AgentResponse(
                    text="",
                    tool_calls=(
                        ToolCall(
                            id="call-x",
                            name="send_event",
                            arguments={
                                "event_name": "workflow_phase_complete",
                                "data": {
                                    "workflow": "risk-review",
                                    "voice": "doktor",
                                    "phase_id": "draft",
                                    "deliverables": ["risks.md"],
                                    "checkpoint_results": [
                                        {"checkpoint": "risks.md exists", "passed": False},
                                    ],
                                },
                                "target": "workflow_engine",
                            },
                        ),
                    ),
                )
            else:
                # Terminal text-only turn ends the agent loop.
                yield AgentResponse(text="Checkpoint reported.", tool_calls=())

    voice = _make_voice(tmp_path, provider=_FailingProvider())
    voice._settings = VoiceSettings(stream=True)
    await manager.enable_plugin(voice)
    await manager.wait_for_idle(timeout=5)

    try:
        await manager.emit(
            "workflow_run",
            WorkflowRunData(workflow="risk-review", voice="doktor"),
            source="test",
        )
        await manager.wait_for_idle(timeout=15)

        # Then: the engine paused on the failed checkpoint — no silent success.
        snapshot = WorkflowEngine(config_dir=tmp_path).snapshot(
            workflow="risk-review", voice="doktor"
        )
        assert snapshot is None or snapshot.status != "completed"
        assert not (tmp_path / "risks.md").exists()

        from kateto.core.event import WorkflowCheckpointFailData

        fails = [
            e.data
            for e in manager.get_events()
            if isinstance(e.data, WorkflowCheckpointFailData)
        ]
        assert len(fails) == 1 and fails[0].checkpoint == "risks.md exists"
    finally:
        await manager.close()
