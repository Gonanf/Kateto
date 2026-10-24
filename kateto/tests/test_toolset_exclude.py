import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from openai.types.chat import ChatCompletionToolParam

from kateto.core.config import VoiceSettings
from kateto.voices.base import VoiceAgent, VoiceProfile, VoiceRole
from kateto.voices.factory import (
    _CAPABILITIES_BY_NAME,
    _TOOLSET_EXCLUDED,
    _capabilities_excluded,
)
from kateto.voices.tools import (
    BUILTIN_TOOLS,
    KatetoToolset,
    filter_tool_names,
)


def test_default_does_not_change_anything() -> None:
    # Given: default VoiceSettings instance
    # When: inspecting default configuration values
    settings = VoiceSettings()

    # Then: toolset_exclude and capabilities_exclude are empty lists, and exclusion returns empty set
    assert settings.toolset_exclude == []
    assert settings.capabilities_exclude == []
    assert _capabilities_excluded([]) == frozenset()


def test_work_builtin_tools_excluded() -> None:
    # Given: work tools to be excluded
    work_tools = [
        "request_generation",
        "schedule_event",
        "create_workflow",
        "update_workflow",
        "create_skill",
        "update_skill",
    ]
    executor = SimpleNamespace(_disable_scheduling_tools=False)

    # When: KatetoToolset is built with excluded work tools and baseline exclusions
    ts = KatetoToolset(
        executor,  # type: ignore[arg-type]
        exclude_names=_TOOLSET_EXCLUDED | frozenset(work_tools),
    )
    exposed_names = set(ts.toolset.tools.keys())

    # Then: work tools are not exposed
    for tool_name in work_tools:
        assert tool_name not in exposed_names

    # And: runtime/non-work tools are exposed
    expected_included = [
        "send_event",
        "list_events",
        "update_soul",
        "refine_memory",
        "get_current_time",
        "enable_plugin",
        "disable_plugin",
        "list_plugins",
    ]
    for tool_name in expected_included:
        assert tool_name in exposed_names


def test_event_tools_filtered() -> None:
    # Given: sample tool definitions including work events and audio/speech events
    sample_tools = (
        ChatCompletionToolParam(type="function", function={"name": "backlog_add"}),
        ChatCompletionToolParam(type="function", function={"name": "workflow_run"}),
        ChatCompletionToolParam(type="function", function={"name": "cli_execute"}),
        ChatCompletionToolParam(type="function", function={"name": "audio_output"}),
        ChatCompletionToolParam(type="function", function={"name": "speak"}),
        ChatCompletionToolParam(type="function", function={"name": "generate"}),
    )
    excluded = frozenset({"backlog_add", "workflow_run", "cli_execute"})

    # When: filtering tool names
    filtered = filter_tool_names(sample_tools, excluded)
    filtered_names = tuple(t["function"]["name"] for t in filtered)

    # Then: only non-excluded tools remain
    assert filtered_names == ("audio_output", "speak", "generate")


def test_capabilities_excluded() -> None:
    # Given: canonical names for work capabilities
    work_caps = [
        "code_mode",
        "shell",
        "workflow",
        "planning",
        "capability_creation",
        "filesystem",
    ]

    # When: resolving excluded capability class names
    excluded_classes = _capabilities_excluded(work_caps)

    # Then: exactly the corresponding class names are returned
    expected = frozenset({
        "CodeMode",
        "Shell",
        "WorkflowCapability",
        "Planning",
        "CapabilityCreation",
        "FileSystem",
    })
    assert excluded_classes == expected

    # And: empty list returns empty frozenset
    assert _capabilities_excluded([]) == frozenset()


def test_anti_empty_guarantee() -> None:
    # Given: work tools list and builtin tools registry
    work_tools = [
        "request_generation",
        "schedule_event",
        "create_workflow",
        "update_workflow",
        "create_skill",
        "update_skill",
    ]
    builtin_names = {t["function"]["name"] for t in BUILTIN_TOOLS}

    # Then: every work tool name must genuinely exist in BUILTIN_TOOLS
    for name in work_tools:
        assert name in builtin_names, f"Work tool '{name}' does not exist in BUILTIN_TOOLS"

    # And: every canonical capability name in _CAPABILITIES_BY_NAME must be recognized
    for canonical_name, class_name in _CAPABILITIES_BY_NAME.items():
        assert _capabilities_excluded([canonical_name]) == frozenset({class_name}), (
            f"Capability '{canonical_name}' was not mapped to '{class_name}'"
        )


@pytest.mark.asyncio
async def test_delegation_block_excluded_when_request_generation_excluded(tmp_path) -> None:
    # Given: a voice profile and provider
    profile = VoiceProfile(
        voice_id="test_voice",
        display_name="Test Voice",
        role=VoiceRole.IMPROVISER,
        system_prompt="Test system prompt.",
        relevance_terms=frozenset({"test"}),
    )

    # When: voice is created with default settings and attached to a pydantic agent
    voice_default = VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(),
    )
    voice_default.set_pydantic_agent(MagicMock())
    prompt_default = await voice_default._stable_prompt()

    # Then: stable prompt contains delegation instructions
    assert "DELEGATION INSTRUCTION" in prompt_default

    # When: voice is created with request_generation excluded
    voice_excluded = VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(toolset_exclude=["request_generation"]),
    )
    voice_excluded.set_pydantic_agent(MagicMock())
    prompt_excluded = await voice_excluded._stable_prompt()

    # Then: stable prompt does NOT contain delegation instructions
    assert "DELEGATION INSTRUCTION" not in prompt_excluded
