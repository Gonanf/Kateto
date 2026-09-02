from __future__ import annotations

from typing import Any, Callable


def _boson_prompt_block() -> str:
    return (
        "AUDIO GENERATION INSTRUCTION (Boson Higgs-TTS 3):\n"
        "Your speech is synthesized by Boson Higgs-TTS 3. You can control delivery, emotion, style, prosody, and vocal sound effects using inline control tokens:\n\n"
        "1. EMOTION TAGS (<|emotion:...|>):\n"
        "   - Set the overall emotion: elation, amusement, enthusiasm, determination, pride, contentment, affection, relief, contemplation, confusion, surprise, awe, longing, arousal, anger, fear, disgust, bitterness, sadness, shame, helplessness.\n"
        "   - Example: '<|emotion:enthusiasm|>¡Esto va a ser increíble!' or '<|emotion:contemplation|>A veces me pregunto qué significa realmente todo esto.'\n\n"
        "2. STYLE TAGS (<|style:...|>):\n"
        "   - whispering, shouting, singing.\n"
        "   - Example: '<|style:whispering|>Acércate, tengo un secreto...' or '<|style:shouting|>¡Oigan todos, presten atención ahora mismo!'\n\n"
        "3. PROSODY TAGS (<|prosody:...|>):\n"
        "   - Speed: speed_very_slow (~0.65x), speed_slow (~0.85x), speed_fast (~1.2x), speed_very_fast (~1.4x).\n"
        "   - Pitch: pitch_low (~-3 semitones), pitch_high (~+2.5 semitones).\n"
        "   - Expressiveness: expressive_high (dynamic delivery), expressive_low (flatter delivery).\n"
        "   - Pauses: <|prosody:pause|> (~400-700ms), <|prosody:long_pause|> (~700-1500ms).\n"
        "   - Example: '<|prosody:speed_fast|>Rápido, rápido, no hay tiempo que perder.' or 'Espera un momento... <|prosody:pause|> y aquí está el gran resultado.'\n\n"
        "4. VOCAL SOUND EFFECTS (<|sfx:...|>):\n"
        "   - cough, laughter, crying, screaming, burping, humming, sigh, sniff, sneeze.\n"
        "   - RULE FOR SFX: Always pair every sound effect immediately with written onomatopoeia/vocal cue so the model realizes it:\n"
        "     e.g., '<|sfx:laughter|>Haha, ¡qué gracioso!' | '<|sfx:sigh|>Uff, qué alivio.' | '<|sfx:cough|>Ahem, disculpen.' | '<|sfx:sneeze|>¡Achoo!' | '<|sfx:humming|>Hmm, buena pregunta.'\n\n"
        "PLACEMENT RULES:\n"
        "- Turn-level delivery tokens (emotion, style, speed, pitch, expressiveness) MUST be placed at the very start of the turn before any spoken text.\n"
        "- Positional tokens (<|prosody:pause|>, <|prosody:long_pause|>) go exactly where the pause should occur.\n"
        "- SFX tokens (<|sfx:...|>) go right before their onomatopoeic word.\n"
        "- Combine naturally: '<|emotion:amusement|><|sfx:laughter|>Haha, <|prosody:pause|> eso no me lo esperaba.'"
    )


def _edgetts_prompt_block() -> str:
    return (
        "AUDIO GENERATION INSTRUCTION (Edge TTS):\n"
        "Your speech is synthesized by Edge TTS neural voices. "
        "Speak in clear, natural, expressive sentences. Avoid inline markup tags, code blocks, or unnatural punctuation."
    )


_PROMPT_BLOCK_REGISTRY: dict[str, Callable[[], str]] = {
    "boson": _boson_prompt_block,
    "edgetts": _edgetts_prompt_block,
    "edge_tts": _edgetts_prompt_block,
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
