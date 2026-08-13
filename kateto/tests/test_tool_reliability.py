from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData, TextChunk
from kateto.providers.agent import ToolCall
from kateto.tests.faux_provider import FauxProvider, FauxResponseStep
from kateto.voices.base import VoiceAgent
from kateto.voices.tools import (
    BUILTIN_TOOLS,
    VoiceToolExecutor,
    is_terminal_tool,
    preflight_tool_arguments,
    sanitize_string,
    turn_is_truncated,
)


def _tc(name: str = "write_file", args: dict | None = None) -> ToolCall:
    return ToolCall(id="1", name=name, arguments=args or {})


# --- pure guard seam ---


def test_turn_is_truncated_only_fires_on_length_with_tool_calls() -> None:
    # Given: a turn with a truncated stop reason and/or tool calls
    # Then: the guard only blocks when BOTH are present
    assert turn_is_truncated("length", (_tc(),)) is True
    assert turn_is_truncated("length", ()) is False
    assert turn_is_truncated("stop", (_tc(),)) is False
    assert turn_is_truncated(None, (_tc(),)) is False


def test_preflight_rejects_missing_required_and_wrong_types() -> None:
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    # When: required args are missing or mistyped
    cleaned, error = preflight_tool_arguments(schema, {})
    assert cleaned is None and "missing required argument: path" in error
    cleaned, error = preflight_tool_arguments(schema, {"path": 42})
    assert cleaned is None and "argument 'path' must be a string" in error


def test_preflight_sanitizes_control_chars_and_passes_valid_args() -> None:
    # Given: args carrying control characters inside strings
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    }
    # When: preflight sanitizes them
    cleaned, error = preflight_tool_arguments(schema, {"path": "a\x1fb.md", "content": "ok\x07"})
    # Then: control chars are stripped and valid args pass
    assert error is None
    assert cleaned == {"path": "ab.md", "content": "ok"}
    assert sanitize_string("keep\ttab\nnewline\r") == "keep\ttab\nnewline\r"


def test_request_generation_declares_terminate() -> None:
    # Given: the built-in toolset
    # Then: request_generation closes the turn, other tools do not
    request_gen = next(t for t in BUILTIN_TOOLS if t["function"]["name"] == "request_generation")
    assert is_terminal_tool(request_gen["function"]["name"]) is True
    assert is_terminal_tool(BUILTIN_TOOLS[0]["function"]["name"]) is False


# --- loop-level guard through the real bus ---


def _make_voice(tmp_path: Path, *, stream: bool) -> VoiceAgent:
    from kateto.voices.factory import _PROFILES

    return VoiceAgent(
        profile=_PROFILES["jane"],
        config_dir=tmp_path,
        provider=object(),  # unused: the agent loop talks to the FauxProvider
        settings=VoiceSettings(stream=stream),
    )


async def _run_script(
    tmp_path: Path,
    script: list[FauxResponseStep],
    *,
    stream: bool = True,
) -> tuple[PluginManager, FauxProvider]:
    manager = PluginManager()
    faux = FauxProvider(script, stream=stream)
    executor = VoiceToolExecutor(
        config_dir=tmp_path, working_directory=tmp_path, manager=manager, voice_name="jane"
    )
    voice = _make_voice(tmp_path, stream=stream)
    voice.setup_agent(agent_provider=faux, tool_executor=executor)
    await manager.enable_plugin(voice)
    await manager.emit("generate", GenerateData(prompt="do the work"), source="fixture", target="jane")
    await manager.wait_for_idle(timeout=5)
    return manager, faux


def _tool_messages(faux: FauxProvider) -> list[str]:
    return [m["content"] for m in faux.requests[0] if m["role"] == "tool"]


@pytest.mark.asyncio
async def test_truncated_turn_never_executes_tools(tmp_path: Path) -> None:
    # Given: a turn whose tool call arrives with stop_reason == "length"
    script = [
        FauxResponseStep(
            tool_calls=(_tc("write_file", {"path": "victim.md", "content": "boom"}),),
            stop_reason="length",
        ),
    ]
    # When: the voice runs the turn
    manager, faux = await _run_script(tmp_path, script)
    # Then: nothing executes, the model gets a structured error, and a fresh
    # LLM call follows so the model can retry
    assert not (tmp_path / "victim.md").exists()
    assert any("truncated" in content for content in _tool_messages(faux))
    results = [e.data for e in manager.get_events() if e.name == "tool_result"]
    assert results and results[0].error and "truncated" in results[0].error
    assert faux.calls == 2


@pytest.mark.asyncio
async def test_truncated_turn_never_executes_tools_non_stream(tmp_path: Path) -> None:
    # Given: the same truncated turn through the non-streaming chat_with_tools path
    script = [
        FauxResponseStep(
            tool_calls=(_tc("write_file", {"path": "victim.md", "content": "boom"}),),
            stop_reason="length",
        ),
    ]
    manager, faux = await _run_script(tmp_path, script, stream=False)
    # Then: the same guard applies
    assert not (tmp_path / "victim.md").exists()
    assert any("truncated" in content for content in _tool_messages(faux))
    results = [e.data for e in manager.get_events() if e.name == "tool_result"]
    assert results and results[0].error and "truncated" in results[0].error


@pytest.mark.asyncio
async def test_preflight_rejects_bad_arguments_in_loop(tmp_path: Path) -> None:
    # Given: a write_file call missing its required content argument
    script = [FauxResponseStep(tool_calls=(_tc("write_file", {"path": "victim.md"}),))]
    manager, faux = await _run_script(tmp_path, script)
    # When: the voice runs the turn
    # Then: the tool never executes and the model receives the validation error
    assert not (tmp_path / "victim.md").exists()
    assert any("missing required argument: content" in content for content in _tool_messages(faux))
    results = [e.data for e in manager.get_events() if e.name == "tool_result"]
    assert results and results[0].error and "missing required argument" in results[0].error


@pytest.mark.asyncio
async def test_terminal_tool_skips_followup_llm_call(tmp_path: Path) -> None:
    # Given: a turn whose only tool call is request_generation (a terminal tool)
    script = [
        FauxResponseStep(
            tool_calls=(_tc("request_generation", {"target_voice": "doktor", "prompt": "plan the week"}),),
        ),
    ]
    # When: the voice runs the turn
    manager, faux = await _run_script(tmp_path, script)
    # Then: the delegation fires and the "listo" round-trip is skipped
    assert faux.calls == 1
    assert [e for e in manager.get_events() if e.name == "generate_request"]


@pytest.mark.asyncio
async def test_faux_3_step_script_runs_full_pipeline(tmp_path: Path) -> None:
    # Given: a scripted 3-step turn (chunks + tool + final) and a file to read
    (tmp_path / "plan.md").write_text("ship it", encoding="utf-8")
    script = [
        FauxResponseStep(
            chunks=("Checking", " plan..."),
            tool_calls=(_tc("read_file", {"path": "plan.md"}),),
        ),
        FauxResponseStep(chunks=("Plan", " found.")),
    ]
    # When: the voice runs the full pipeline in milliseconds without any LLM
    manager, faux = await _run_script(tmp_path, script)
    # Then: streamed text is spoken, the tool executed, and the final text lands
    assert faux.calls == 2
    spoken = [
        e.data.text
        for e in manager.get_events()
        if e.name == "text_chunk" and isinstance(e.data, TextChunk) and e.data.text
    ]
    assert "Checking" in "".join(spoken) and "Plan found." in "".join(spoken)
    results = [e.data for e in manager.get_events() if e.name == "tool_result"]
    assert results and results[0].error is None and "ship it" in results[0].result