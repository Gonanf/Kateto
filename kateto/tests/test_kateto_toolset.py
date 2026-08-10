import json
from pathlib import Path

import pytest

from kateto.voices.tools import BUILTIN_TOOLS, KatetoToolset, VoiceToolExecutor


def test_builtin_tools_all_declare_parameter_schemas():
    # Given: the tools advertised to models
    # Then: every one must carry a JSON schema with named properties
    for tool in BUILTIN_TOOLS:
        function = tool["function"]
        name = function["name"]
        parameters = function.get("parameters") or {}
        assert isinstance(parameters, dict), f"{name} has no parameters schema"
        assert parameters.get("type") == "object", f"{name} parameters must be an object"
        assert isinstance(parameters.get("properties", {}), dict), f"{name} properties missing"
        assert function.get("description"), f"{name} has no description"


@pytest.mark.asyncio
async def test_toolset_prepare_injects_real_schemas(tmp_path):
    # Given: the pydantic-ai toolset built from BUILTIN_TOOLS
    executor = VoiceToolExecutor(config_dir=tmp_path)
    toolset = KatetoToolset(executor).toolset
    expected = {t["function"]["name"]: t["function"].get("parameters") or {} for t in BUILTIN_TOOLS}

    # When: each tool definition is prepared for a run
    for name, tool in toolset.tools.items():
        tool_def = await tool.prepare_tool_def(object())

        # Then: the schema matches the real BUILTIN_TOOLS parameters
        assert tool_def is not None, f"{name} produced no tool definition"
        schema = tool_def.parameters_json_schema
        assert name in expected, f"toolset exposes unexpected tool {name}"
        assert schema == expected[name], f"{name} schema not injected: {schema}"


@pytest.mark.asyncio
async def test_delete_file_tool_roundtrip(tmp_path):
    # Given: a file in the working directory
    executor = VoiceToolExecutor(config_dir=tmp_path)
    target = tmp_path / "scratch.md"
    target.write_text("obsolete", encoding="utf-8")

    # When: delete_file is invoked on it
    result = json.loads(await executor.execute("delete_file", {"path": "scratch.md"}))

    # Then: the file is removed and the result confirms it
    assert result == {"deleted": "scratch.md"}
    assert not target.exists()


@pytest.mark.asyncio
async def test_delete_file_rejects_escape_and_missing(tmp_path):
    # Given: an executor rooted in tmp_path
    executor = VoiceToolExecutor(config_dir=tmp_path)

    # When: deleting outside the working directory or a nonexistent file
    escape = json.loads(await executor.execute("delete_file", {"path": "../outside.md"}))
    missing = json.loads(await executor.execute("delete_file", {"path": "nope.md"}))

    # Then: both fail safely
    assert "error" in escape
    assert "error" in missing
