from __future__ import annotations

from typing import Any, Callable


def _boson_prompt_block() -> str:
    return (
        "AUDIO GENERATION INSTRUCTION (Boson TTS): Output text will be spoken via Boson TTS. "
        "Keep speech expressive, natural, and avoid unpronounceable characters or code blocks."
    )


_PROMPT_BLOCK_REGISTRY: dict[str, Callable[[], str]] = {
    "boson": _boson_prompt_block,
}


def get_agent_prompt_block(provider: str) -> str | None:
    fn = _PROMPT_BLOCK_REGISTRY.get(provider.lower())
    if fn is not None:
        return fn()
    return None


def get_workflow_prompt_block(available_workflows: tuple[Any, ...] | None = None) -> str:
    lines = [
        "WORKFLOW SYSTEM INSTRUCTION:",
        "Workflows provide structured multi-phase guidance for project goals.",
    ]
    if available_workflows:
        formatted = "\n".join(f"- {w.name}: {w.description}" for w in available_workflows)
        lines.append(f"Available Workflows for this voice:\n{formatted}")
    lines.append(
        "HOW TO USE WORKFLOWS:\n"
        "- Workflows execute structured phases with tasks, deliverables, and checkpoints.\n"
        "- To start a workflow, emit the `workflow_run` event with `workflow` (the exact workflow name) and `voice` (your voice ID).\n"
        "- To create or edit a workflow definition, use the `create_workflow` or `update_workflow` tools.\n"
        "- If currently in a phase, finish deliverables and emit `workflow_phase_complete`."
    )
    return "\n".join(lines)


def get_mcp_prompt_block(mcp_server_names: tuple[str, ...] | None = None) -> str:
    lines = [
        "MCP (MODEL CONTEXT PROTOCOL) INSTRUCTION:",
        "You have access to Model Context Protocol (MCP) tools and integrations.",
    ]
    if mcp_server_names:
        lines.append(f"Connected MCP Servers: {', '.join(mcp_server_names)}")
    lines.append(
        "HOW TO USE MCP TOOLS:\n"
        "- Call available MCP tools by name to query external systems, execute allowed CLI tools, or access resources.\n"
        "- Tool results are dispatched back as event results for seamless context synthesis."
    )
    return "\n".join(lines)


def get_delegation_prompt_block() -> str:
    return (
        "DELEGATION INSTRUCTION:\n"
        "- You can ask other voices for input. Use `request_generation(target_voice, prompt)` "
        "to request a spoken response from another team member.\n"
        "- Use `directory_voices()` to list the team and their departments before delegating, "
        "and `directory_plugins()` / `directory_events()` to inspect the runtime.\n"
        "- Delegate specialized work to the right voice instead of doing it yourself."
    )
