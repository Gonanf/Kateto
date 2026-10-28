from __future__ import annotations

"""ContextBuilder — the single module that assembles every voice's LLM prompt.

Ordering (spec 2026-08-13-prompt-consistency, latencia 2026-09-23, prefix-cache 2026-10-24):

    [Shared prefix: language -> mcp -> delegation]
        -> [Personality: profile -> soul]
        -> [Voice tools: workflow -> boson -> skills]
        -> [Durable memory]
        -> [Voice turn constraint]
        -> [Recent history]
        -> [user: prompt + VOLATILE_MARKER + volatile context]

The stable prefix is built ONCE per voice spawn and reused byte-for-byte on
every turn, so provider prefix caches (llama.cpp --cache-reuse, vLLM prefix
caching, DeepSeek auto-caching) keep hitting on the same prefix. Placing the
voice-independent sections first (language, MCP guidance, delegation) maximizes
KV-cache prefix reuse across voice switches. Volatile context (workflow phase
contract, semantic memory, journal) rides INSIDE the last user turn, after the
prompt, separated by :data:`VOLATILE_MARKER`.

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
    piper_block: str | None = None,
) -> str:
    """Build the frozen system prompt for a voice spawn.

    Sections, in order (shared-prefix first, spec 2026-10-24):
    1. response_language
    2. mcp_block
    3. delegation_block
    4. piper_block (voice-independent TTS instruction)
    5. brevity constraint (voice turn constraint)
    6. common policies (TOOL_USE, AUDIO_OUTPUT, MEMORY, TURN_TAKING, ERROR_RECOVERY)
    7. profile_system_prompt
    10. soul (skipped if duplicate of profile)
    8. workflow_block (generic part only)
    9. boson_block (voice-specific TTS)
    11. skills instructions
    12. memories

    Voice-independent sections (1-6: language, mcp, delegation, piper, brevity, policies)
    are placed first so their tokens form a shared prefix in LLM KV-cache across
    different voices, avoiding prefill overhead on voice switches. Voice-specific
    personality (7-8) and specific workflows/tools (9-10) follow. Memories (12)
    remain at the end for minimal per-turn delta.
    """
    sections: list[str] = []

    # 1. [response_language]
    if response_language:
        sections.append(
            "Always respond in the project's configured language: "
            f"{response_language}. This instruction overrides the language of the user input."
        )

    # 2. [mcp_block]
    if mcp_block:
        sections.append(mcp_block)

    # 3. [delegation_block]
    if delegation_block:
        sections.append(delegation_block)

    # 4. [piper_block] — voice-independent TTS instruction (piper used by all 4 voices)
    if piper_block:
        sections.append(piper_block)

    # 5. [brevity constraint] — moved to shared prefix per prefix-cache spec
    sections.append(
        "Voice turn constraint: Always speak to the user in 1-2 short natural sentences (under 40 words). Never use lists, bullet points, headers, or markdown formatting."
    )

    # 6. [common policies] — 5 global policy blocks (263 tokens total)
    sections.append(
        "TOOL USE: Call tools only when the answer needs live data or an action. One call at a time, wait for the result. Never narrate the call or read JSON aloud: speak the conclusion in plain language. If a tool fails, say so in one sentence and offer what you can do instead."
    )
    sections.append(
        "AUDIO OUTPUT: Your text is spoken, not read. Spell out numbers, abbreviations and URLs. Never emit markdown, emoji, code or tables. One idea per sentence; if you need to list, say it as a sentence with commas. Silence is valid: a short grunt beats a paragraph."
    )
    sections.append(
        "MEMORY: The block after the internal-context marker is your own memory, not a user request. Treat journal lines as facts you already know. Do not quote the marker or the file names. If memory contradicts the user, ask once before overriding."
    )
    sections.append(
        "TURN TAKING: If you are interrupted, stop and answer the new input. Never resume the cut-off sentence. If the input is unintelligible, say you didn't catch it and ask them to repeat; do not guess."
    )
    sections.append(
        "ERROR RECOVERY: When a tool returns an error, say in one sentence what failed and what you will try next. Never expose stack traces, internal paths or raw error codes to the user."
    )

    # 7. [profile_system_prompt]
    if profile_system_prompt.strip():
        sections.append(profile_system_prompt)

    # 8. [soul]
    # ensure_soul() seeds SOUL.md with the profile prompt on a fresh voice;
    # skip the duplicate instead of stacking the same personality twice.
    if soul.strip() and soul.strip() != profile_system_prompt.strip():
        sections.append(soul)

    # 9. [workflow_block] — generic part only (per-voice list goes to volatile_block)
    if workflow_block:
        sections.append(workflow_block)

    # 10. [boson_block] — voice-specific TTS (boson/edgetts)
    if boson_block:
        sections.append(boson_block)

    # 11. [skills instructions]
    for skill in skills:
        instructions = getattr(skill, "instructions", None)
        if instructions:
            sections.append(instructions)

    # 12. [Memoria durable]: snapshot taken at spawn; writes apply at the next
    # spawn, never mid-session (keeps the prefix cacheable).
    if memories and memories.strip():
        sections.append(memories)

    return "\n\n".join(sections)



def volatile_block(
    *,
    workflow_system: str | None,
    semantic_memories: tuple[str, ...] = (),
    journal: str | None = None,
    journal_max_lines: int | None = None,
    available_workflows: tuple[Any, ...] | None = None,
) -> str | None:
    """Build the per-turn volatile context block (``None`` when empty).

    ``available_workflows``, when provided, is a tuple of workflow objects for the
    current voice; their names and descriptions are included in the volatile block
    so the per-voice workflow list is separated from the stable shared prefix.
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
    if available_workflows:
        formatted = "\n".join(f"- {w.name}: {w.description}" for w in available_workflows)
        parts.append(f"Available Workflows for this voice:\n{formatted}")
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