from __future__ import annotations

"""ContextBuilder — the single module that assembles every voice's LLM prompt.

Ordering (spec 2026-08-13-prompt-consistency, latencia 2026-09-23):

    [SOUL stable] -> [Tool schemas] -> [Durable memory] -> [Recent history]
        -> [user: prompt + VOLATILE_MARKER + volatile context]

The stable prefix (sections 1-3 plus fixed guidance) is built ONCE per voice
spawn and reused byte-for-byte on every turn, so provider prefix caches
(llama.cpp --cache-reuse, vLLM prefix caching, DeepSeek auto-caching) keep
hitting on the same prefix. Volatile context (workflow phase contract,
semantic memory, journal) rides INSIDE the last user turn, after the prompt,
separated by :data:`VOLATILE_MARKER`.

Why not a dedicated system message after the user (2026-09-23)? Three reasons:
1. Lynneses de API distintas: varios gateways remotos reordenan o descartan un
   system message que aparece DESPUÉS de un mensaje de usuario.
2. El camino pydantic-ai filtra history a roles ("assistant", "user") — un
   system intercalado se descartaría (misma razón que IGNORED_TRANSCRIPT_PREFIX
   en base.py: el contenido que debe llegar a ambos caminos va en el content
   del mensaje user).
3. El journal crece una línea por turno: cuanto más tarde quede en el prompt,
   menos tokens cambian entre turnos y menos re-prefill paga cada generación.

Prompt caching contract:
- ``prompt_cache_key`` is a fixed per-voice key (``kateto-voice-<voice_id>``).
- ``session_headers`` carries the per-session id plus the cache key so an
  OpenAI-compatible provider that honors session affinity can group requests.
- Background traffic (classifier, summaries) never sets these headers and uses
  its own model/endpoint, so it cannot evict a live voice's cached prefix.
"""

from kateto.providers import ChatMessage

__all__ = [
    "VOLATILE_MARKER",
    "assemble_messages",
    "prompt_cache_key",
    "session_headers",
    "stable_prompt",
    "volatile_block",
]

# Separador entre el pedido del usuario y el contexto volátil que viaja en el
# mismo turno. El modelo lee el bloque como memoria del sistema, no como un
# segundo pedido.
VOLATILE_MARKER = "[CONTEXTO INTERNO — memoria del sistema, no es el pedido del usuario]"


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

    # [Restricción de brevedad de voz]: acota el turno conversacional a 1-2
    # oraciones naturales (< 40 palabras) para evitar desbordes y finish_reason=length.
    sections.append(
        "Voice turn constraint: Always speak to the user in 1-2 short natural sentences (under 40 words). Never use lists, bullet points, headers, or markdown formatting."
    )

    return "\n\n".join(sections)



def volatile_block(
    *,
    workflow_system: str | None,
    semantic_memories: tuple[str, ...] = (),
    journal: str | None = None,
    journal_max_lines: int | None = None,
) -> str | None:
    """Build the per-turn volatile context block (``None`` when empty).

    ``journal_max_lines`` caps the journal to its last N non-blank lines at
    assembly time — the JOURNAL.md file is never touched, so the knob only
    bounds the per-turn context and re-prefill, never the user's memory.
    """
    parts: list[str] = []
    if workflow_system:
        parts.append(workflow_system)
    if semantic_memories:
        parts.append("Relevant memories:\n" + "\n".join(f"- {memory}" for memory in semantic_memories))
    if journal and journal.strip():
        journal = _cap_journal(journal, journal_max_lines)
        if journal:
            parts.append(journal)
    return "\n\n".join(parts) if parts else None


def _cap_journal(journal: str, journal_max_lines: int | None) -> str:
    if journal_max_lines is None:
        return journal
    if journal_max_lines <= 0:
        return ""
    lines = [line for line in journal.splitlines() if line.strip()]
    return "\n".join(lines[-journal_max_lines:])


def assemble_messages(
    *,
    stable: str,
    history: tuple[ChatMessage, ...],
    volatile: str | None,
    prompt: str,
) -> tuple[ChatMessage, ...]:
    """Assemble the ordered message structure for a voice turn.

    [system: stable prefix] -> [recent history]
        -> [user: prompt + VOLATILE_MARKER + volatile context]
    """
    messages = [ChatMessage(role="system", content=stable)]
    messages.extend(history)
    if volatile:
        content = f"{prompt}\n\n{VOLATILE_MARKER}\n\n{volatile}"
        messages.append(ChatMessage(role="user", content=content))
    else:
        messages.append(ChatMessage(role="user", content=prompt))
    return tuple(messages)