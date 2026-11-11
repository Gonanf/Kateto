from __future__ import annotations

"""Sanitizer for voice output — strips accidental tool-call locutions before TTS."""

import re

REPO_TOOL_NAMES = frozenset({
    "run_command",
    "read_file",
    "write_file",
    "delete_file",
    "send_event",
    "list_events",
    "enable_plugin",
    "disable_plugin",
    "list_plugins",
    "create_skill",
    "update_skill",
    "create_workflow",
    "update_workflow",
    "update_soul",
    "request_generation",
    "schedule_event",
    "get_current_time",
    "refine_memory",
    "workflow_run",
    "workflow_started",
    "workflow_stop",
    "workflow_stopped",
    "workflow_phase_start",
    "workflow_phase_complete",
    "workflow_checkpoint_fail",
    "workflow_completed",
    "directory_voices",
    "directory_plugins",
    "directory_events",
})

_TOOLS_REGEX = "|".join(re.escape(name) for name in sorted(REPO_TOOL_NAMES, key=len, reverse=True))

# 1. Code blocks containing tool calls
_CODE_BLOCK_PATTERN = re.compile(
    rf"```(?:[a-zA-Z0-9_+-]*\n)?\s*(?:(?:{_TOOLS_REGEX})[^\n]*\n?)+\s*```\s*",
    re.IGNORECASE,
)

# 2. CLI / keyword / positional syntax at line start: tool arg=val or tool arg val
_CLI_PATTERN = re.compile(
    rf"^\s*(?:{_TOOLS_REGEX})(?:\s+[\w\-]+(?:=[\w\-'\"\s/]+)?)+\s*(?:\n+|$)",
    re.IGNORECASE | re.MULTILINE,
)

# 3. Function call syntax: tool(...) or any_id(workflow=... or voice=...)
_FUNC_PATTERN = re.compile(
    rf"(?:(?:(?:{_TOOLS_REGEX})\s*\([^)]*\))|(?:[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*(?:workflow|voice|target_voice|prompt)\s*=[^)]*\)))\s*",
    re.IGNORECASE,
)


def sanitize_voice_output(text: str) -> str:
    """Sanitize voice text before TTS locution.

    Strips leaked tool invocations (function calls, CLI syntax, markdown code blocks)
    while preserving genuine character dialogue and expressions with parentheses.
    """
    if not text:
        return text

    # Strip code blocks with tool calls
    cleaned = _CODE_BLOCK_PATTERN.sub("", text)
    # Strip CLI-style tool calls
    cleaned = _CLI_PATTERN.sub("", cleaned)
    # Strip function-call tool calls
    cleaned = _FUNC_PATTERN.sub("", cleaned)

    return cleaned.strip()
