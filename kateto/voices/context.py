from __future__ import annotations

"""ContextBuilder — the single module that assembles every voice's LLM prompt.

Ordering (spec 2026-08-13-prompt-consistency, brainstorming §A2/G2/H1):

    [SOUL stable] -> [Tool schemas] -> [Durable memory] -> [Recent history] -> [Volatile context]

The stable prefix (sections 1-3 plus fixed guidance) is built ONCE per voice
spawn and reused byte-for-byte on every turn, so provider prefix caches
(llama.cpp --cache-reuse, vLLM prefix caching, DeepSeek auto-caching) keep
hitting on the same prefix. Volatile context (workflow phase contract,
semantic memory, journal) is appended at the END of the message structure and
never touches the frozen prefix.

Prompt caching contract:
- ``prompt_cache_key`` is a fixed per-voice key (``kateto-voice-<voice_id>``).
- ``session_headers`` carries the per-session id plus the cache key so an
  OpenAI-compatible provider that honors session affinity can group requests.
- Background traffic (classifier, summaries) never sets these headers and uses
  its own model/endpoint, so it cannot evict a live voice's cached prefix.
"""

from kateto.providers import ChatMessage

__all__ = [
    "assemble_messages",
    "prompt_cache_key",
    "session_headers",
    "stable_prompt",
    "volatile_block",
]


def prompt_cache_key(voice_id: str) -> str:
    """Fixed, byte-stable cache key for a voice (``kateto-voice-<voice_id>``)."""
    return f"kateto-voice-{voice_id.casefold()}"


def session_headers(voice_id: str, session_id: str) -> dict[str, str]:
    """Per-session headers sent with every voice LLM request.

    ``x-session-id`` identifies the session; ``x-session-affinity`` lets
    providers that support session affinity route/group by the voice's fixed
    cache key so the stable prefix stays warm.
    """
    return {
        "x-session-id": session_id,
        "x-session-affinity": prompt_cache_key(voice_id),
    }


def stable_prompt(
    *,
    soul: str,
    profile_system_prompt: str,
    response_language: str | None,
    workflow_block: str | None,
    mcp_block: str | None,
    delegation_block: str | None,
    boson_block: str | None,
    skills: tuple[object, ...],
    memories: str | None,
) -> str:
    """Build the frozen system prompt for a voice spawn.

    Sections, in order: [SOUL stable] -> [Tool schemas/guidance] -> [Durable
    memory]. This string MUST NOT change during a conversation: it is the
    reusable cache prefix. Per-turn context belongs in :func:`volatile_block`.
    """
    sections: list[str] = []

    # [SOUL estable]
    if profile_system_prompt.strip():
        sections.append(profile_system_prompt)
    # ensure_soul() seeds SOUL.md with the profile prompt on a fresh voice;
    # skip the duplicate instead of stacking the same personality twice.
    if soul.strip() and soul.strip() != profile_system_prompt.strip():
        sections.append(soul)
    if response_language:
        sections.append(
            "Always respond in the project's configured language: "
            f"{response_language}. This instruction overrides the language of the user input."
        )

    # [Tool schemas + guidance]: the actual tool JSON schemas ride in the API
    # request (stable per spawn); the text guidance blocks are frozen here so
    # they never change mid-session.
    for block in (workflow_block, mcp_block, delegation_block, boson_block):
        if block:
            sections.append(block)
    for skill in skills:
        instructions = getattr(skill, "instructions", None)
        if instructions:
            sections.append(instructions)

    # [Memoria durable]: snapshot taken at spawn; writes apply at the next
    # spawn, never mid-session (keeps the prefix cacheable).
    if memories and memories.strip():
        sections.append(memories)

    return "\n\n".join(sections)


def volatile_block(
    *,
    workflow_system: str | None,
    semantic_memories: tuple[str, ...] = (),
    journal: str | None = None,
) -> str | None:
    """Build the per-turn volatile context block (``None`` when empty).

    Lives at the END of the message structure, after the recent history, so
    the frozen prefix stays byte-stable across turns.
    """
    parts: list[str] = []
    if workflow_system:
        parts.append(workflow_system)
    if semantic_memories:
        parts.append("Relevant memories:\n" + "\n".join(f"- {memory}" for memory in semantic_memories))
    if journal and journal.strip():
        parts.append(journal)
    return "\n\n".join(parts) if parts else None


def assemble_messages(
    *,
    stable: str,
    history: tuple[ChatMessage, ...],
    volatile: str | None,
    prompt: str,
) -> tuple[ChatMessage, ...]:
    """Assemble the ordered message structure for a voice turn.

    [system: stable prefix] -> [recent history] -> [system: volatile context] -> [user: prompt]
    """
    messages = [ChatMessage(role="system", content=stable)]
    messages.extend(history)
    if volatile:
        messages.append(ChatMessage(role="system", content=volatile))
    messages.append(ChatMessage(role="user", content=prompt))
    return tuple(messages)