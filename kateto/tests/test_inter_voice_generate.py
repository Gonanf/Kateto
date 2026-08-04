from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.event import GENERATE_REQUEST_MAX_DEPTH, GenerateRequestData
from kateto.voices.base import VoiceAgent

from kateto.tests.conversation_support import StreamingFixtureProvider, write_references


async def _make_voices(
    manager: PluginManager, config_dir: Path
) -> tuple[VoiceAgent, VoiceAgent]:
    write_references(config_dir)
    from kateto.voices.factory import _PROFILES
    jane = VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=config_dir,
        provider=StreamingFixtureProvider(),
    )
    doktor = VoiceAgent(
        profile=_PROFILES["doktor"],
        config_dir=config_dir,
        provider=StreamingFixtureProvider(),
    )
    for voice in (jane, doktor):
        await manager.enable_plugin(voice)
    return jane, doktor


@pytest.mark.asyncio
async def test_generate_request_routes_to_target_voice(tmp_path: Path) -> None:
    # Given: jane (fun) and doktor (management) enabled
    manager = PluginManager()
    jane, doktor = await _make_voices(manager, tmp_path)
    # When: jane requests generation from doktor
    await manager.emit(
        "generate_request",
        GenerateRequestData(
            target_voice="doktor",
            prompt="review my plan",
            source_voice="jane",
            depth=0,
        ),
        source="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: doktor generates a response; jane does not
    assert len(doktor._provider.requests) == 1  # type: ignore[attr-defined]
    assert len(jane._provider.requests) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generate_request_respects_target_only(tmp_path: Path) -> None:
    # Given: two voices enabled
    manager = PluginManager()
    jane, doktor = await _make_voices(manager, tmp_path)
    # When: a request targets doktor
    await manager.emit(
        "generate_request",
        GenerateRequestData(
            target_voice="doktor",
            prompt="please",
            source_voice="jane",
            depth=0,
        ),
        source="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: only the target voice generated
    assert len(doktor._provider.requests) == 1  # type: ignore[attr-defined]
    assert len(jane._provider.requests) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generate_request_depth_cap_blocks_forwarding(tmp_path: Path) -> None:
    # Given: two voices enabled
    manager = PluginManager()
    jane, doktor = await _make_voices(manager, tmp_path)
    # When: a request arrives at the maximum depth
    await manager.emit(
        "generate_request",
        GenerateRequestData(
            target_voice="doktor",
            prompt="stop",
            source_voice="jane",
            depth=GENERATE_REQUEST_MAX_DEPTH,
        ),
        source="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the target does not generate (chain guardrail)
    assert len(doktor._provider.requests) == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generate_request_depth_propagates_through_tool(tmp_path: Path) -> None:
    # Given: doktor configured with a tool-calling agent provider
    from kateto.providers.agent import AgentResponse, ToolCall
    from kateto.voices.tools import VoiceToolExecutor

    class ToolCallingProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_with_tools_stream(self, messages: object, tools: object):
            self.calls += 1
            yield AgentResponse(
                text="",
                tool_calls=[ToolCall(id="1", name="request_generation", arguments={"target_voice": "conquest", "prompt": "hi"})],
            )
            yield AgentResponse(text="done", tool_calls=[])

    manager = PluginManager()
    write_references(tmp_path)
    from kateto.voices.factory import _PROFILES
    doktor = VoiceAgent(
        profile=_PROFILES["doktor"],
        config_dir=tmp_path,
        provider=StreamingFixtureProvider(),
    )
    executor = VoiceToolExecutor(config_dir=tmp_path, manager=manager, voice_name="doktor")
    doktor.setup_agent(agent_provider=ToolCallingProvider(), tool_executor=executor)
    await manager.enable_plugin(doktor)
    # When: doktor receives a generate_request at depth 1 and its tool fires
    await manager.emit(
        "generate_request",
        GenerateRequestData(
            target_voice="doktor",
            prompt="chain",
            source_voice="jane",
            depth=1,
        ),
        source="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the forwarded request carries depth 2
    events = [e for e in manager.get_events() if e.name == "generate_request"]
    assert events, "expected a forwarded generate_request"
    assert events[-1].data.depth == 2
    assert events[-1].data.source_voice == "doktor"


@pytest.mark.asyncio
async def test_voice_cannot_forward_request_into_foreign_department(tmp_path: Path) -> None:
    # Given: jane (fun) and doktor (management) enabled
    manager = PluginManager()
    jane, doktor = await _make_voices(manager, tmp_path)
    # When: jane requests generation into the management department
    await manager.emit(
        "generate_request",
        GenerateRequestData(
            target_voice="doktor",
            prompt="classified",
            source_voice="jane",
            depth=0,
            dept="management",
        ),
        source="jane",
    )
    await manager.wait_for_idle(timeout=5)
    # Then: the request is rejected (anti-spoofing) and the voice stays up
    assert len(doktor._provider.requests) == 0  # type: ignore[attr-defined]
    assert jane.enabled and doktor.enabled


@pytest.mark.asyncio
async def test_request_generation_tool_emits_generate_request(tmp_path: Path) -> None:
    # Given: an executor bound to a voice with a manager
    manager = PluginManager()
    from kateto.voices.tools import VoiceToolExecutor

    executor = VoiceToolExecutor(config_dir=tmp_path, manager=manager, voice_name="jane")

    async def run() -> None:
        result = await executor.execute(
            "request_generation",
            {"target_voice": "doktor", "prompt": "hello there"},
        )
        assert "requested" in result

    await run()
    # Then: the generate_request event was emitted with source and depth
    events = manager.get_events()
    envelope = next(e for e in events if e.name == "generate_request")
    assert envelope.data.source_voice == "jane"
    assert envelope.data.target_voice == "doktor"
    assert envelope.data.depth == 0


@pytest.mark.asyncio
async def test_request_generation_tool_requires_arguments(tmp_path: Path) -> None:
    # Given: an executor with a manager
    manager = PluginManager()
    from kateto.voices.tools import VoiceToolExecutor

    executor = VoiceToolExecutor(config_dir=tmp_path, manager=manager, voice_name="jane")
    # When: the tool is called without target_voice
    result = await executor.execute("request_generation", {"prompt": "x"})
    # Then: it reports the missing argument
    assert "target_voice and prompt are required" in result
