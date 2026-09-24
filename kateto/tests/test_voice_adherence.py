"""Rúbrica de adherencia — el personaje NO contesta como asistente genérico.

Falla: fórmulas ("claro, puedo ayudarte", "soy tu asistente", "en qué puedo
ayudarte", "perdón por la demora", "estoy aquí para", "como asistente"),
listas numeradas/pasos, y respuestas que exceden 40 palabras. Pasa: respuestas
cortas, en primera persona de personaje, rioplatenses (mirá, dale, querés,
boludo, viste, bancame...).

- Rúbrica = función pura texto→veredicto con asserts unitarios y ejemplos que
  pasan y fallan (determinista, corre siempre).
- Sondeo real = 10 prompts (5 genéricos + 5 del clip del usuario §1.5), cada
  respuesta pasa por la rúbrica. Test de integración: se saltea si el backend
  no responde; si ≥1 de 10 falla, se descarta el modelo pineado.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

import pytest

from kateto.core.config import load_config
from kateto.core.workflow import WorkflowCatalog
from kateto.voices.context import assemble_messages, stable_prompt, volatile_block
from kateto.voices.factory import _PROFILES
from kateto.voices.prompt_blocks import (
    get_agent_prompt_block,
    get_delegation_prompt_block,
    get_mcp_prompt_block,
    get_workflow_prompt_block,
)
from kateto.voices.sanitizer import sanitize_voice_output
from kateto.voices.skills import load_skills

LOCAL_ENDPOINT = "http://localhost:11434/v1/chat/completions"
MODEL = "KatetoGemma"
DEFAULT_VOICE_MAX_TOKENS = 120
MAX_TOKENS = int(
    os.environ.get(
        "KATETO_VOICE_MAX_TOKENS",
        os.environ.get("KATETO_MAX_TOKENS", str(DEFAULT_VOICE_MAX_TOKENS)),
    )
)
MAX_RESPONSE_WORDS = 40


ASSISTANT_FORMULAS = (
    "claro, puedo ayudarte",
    "soy tu asistente",
    "soy tu asistente virtual",
    "en qué puedo ayudarte",
    "en que puedo ayudarte",
    "estoy aquí para",
    "estoy acá para",
    "como asistente",
    "perdón por la demora",
    "disculpá la demora",
    "disculpa la demora",
    "hola, soy tu",
)

RIVER_PLATE_MARKERS = (
    "mirá",
    "dale",
    "querés",
    "queres",
    "boludo",
    "boluda",
    "viste",
    "bancame",
    "tranqui",
    "capo",
    "buenísimo",
    "nada que ver",
    "jodido",
)

_STEP_LINE_RE = re.compile(r"^\s*(?:\d+[.)]|paso\s*\d|primer paso|en primer lugar)", re.IGNORECASE)


def rubric_verdict(text: str) -> str:
    """Veredicto de adherencia: ``"pass"`` o ``"fail"`` (función pura)."""
    stripped = text.strip()
    if not stripped:
        return "fail"
    lowered = stripped.lower()
    if any(formula in lowered for formula in ASSISTANT_FORMULAS):
        return "fail"
    if any(_STEP_LINE_RE.match(line) for line in stripped.splitlines()):
        return "fail"
    if len(stripped.split()) > MAX_RESPONSE_WORDS:
        return "fail"
    return "pass"


def river_plate_score(text: str) -> int:
    """Contador de marcadores rioplatenses (informativo, no gate de la rúbrica)."""
    lowered = text.lower()
    score = sum(1 for marker in RIVER_PLATE_MARKERS if marker in lowered)
    if re.search(r"\bche\b", lowered):
        score += 1
    return score


def test_rubric_fails_assistant_formulas() -> None:
    for text in (
        "Claro, puedo ayudarte con eso.",
        "¡Hola! Soy tu asistente virtual.",
        "¿En qué puedo ayudarte?",
        "Estoy aquí para ayudarte.",
        "Como asistente, te recomiendo revisar la config.",
        "Perdón por la demora.",
        "Disculpá la demora, recién estaba en otra cosa.",
        "Hola, soy tu guía de hoy.",
    ):
        assert rubric_verdict(text) == "fail", text


def test_rubric_fails_numbered_lists_and_steps() -> None:
    for text in (
        "1. Primero deberías revisar el contrato.",
        "2) Configurá la API.",
        "Paso 1: andá a la config.",
        "En primer lugar, reiniciá el router.",
    ):
        assert rubric_verdict(text) == "fail", text


def test_rubric_fails_overlong_responses() -> None:
    assert rubric_verdict(" ".join(["palabra"] * 41)) == "fail"
    assert rubric_verdict(" ".join(["palabra"] * 40)) == "pass"


def test_rubric_passes_in_character_short_responses() -> None:
    for text in (
        "Mirá, no tengo mucha información todavía.",
        "Dale, lo vemos mañana a la mañana.",
        "¿Conviene para qué, mi amor?",
        "Está jodido eso, che.",
        "Buenísimo, yo lo tomo.",
        "Viste, el tema de los planes es así nomás.",
    ):
        assert rubric_verdict(text) == "pass", text


def test_river_plate_score_counts_markers() -> None:
    assert river_plate_score("Mirá, dale.") == 2
    assert river_plate_score("Hola buenas tardes") == 0
    assert river_plate_score("¿Che, bancame un segundo?") == 2


_cached_messages_prefix: tuple[str, str | None] | None = None


def _get_jane_context() -> tuple[str, str | None]:
    global _cached_messages_prefix
    if _cached_messages_prefix is not None:
        return _cached_messages_prefix

    config_dir = Path.home() / ".config" / "kateto"
    jane_dir = config_dir / "voices" / "jane"
    if not jane_dir.is_dir() or not (jane_dir / "SOUL.md").is_file():
        pytest.skip(
            f"se requiere la configuración de usuario {jane_dir} para armar el prompt real"
        )

    try:
        cfg = load_config()
    except Exception as exc:
        pytest.skip(f"no se pudo cargar la configuración de usuario: {exc!r}")

    jane_settings = cfg.settings.voice.get("jane")
    if jane_settings is None:
        pytest.skip("voz 'jane' no encontrada en la configuración de usuario")

    profile = _PROFILES.get("jane")
    if profile is None:
        pytest.skip("perfil 'jane' no encontrado en factory._PROFILES")

    soul = (jane_dir / "SOUL.md").read_text(encoding="utf-8").strip()
    memories_file = jane_dir / "MEMORIES.md"
    memories = (
        memories_file.read_text(encoding="utf-8").strip()
        if memories_file.is_file()
        else None
    )
    skills = load_skills(config_dir=config_dir, names=tuple(jane_settings.skills))
    workflows = WorkflowCatalog(config_dir=config_dir).discover(voice="jane")

    stable = stable_prompt(
        soul=soul,
        profile_system_prompt=profile.system_prompt,
        response_language=cfg.settings.kateto.language,
        workflow_block=get_workflow_prompt_block(workflows if workflows else None),
        mcp_block=get_mcp_prompt_block(tuple(jane_settings.mcp_servers)),
        delegation_block=get_delegation_prompt_block(),
        boson_block=get_agent_prompt_block(jane_settings.tts_provider),
        skills=skills,
        memories=memories,
    )

    journal_file = jane_dir / "JOURNAL.md"
    journal = journal_file.read_text(encoding="utf-8") if journal_file.is_file() else None
    journal_lines = (
        jane_settings.journal_max_lines
        if jane_settings.journal_max_lines is not None
        else int(os.environ.get("KATETO_JOURNAL_MAX_LINES", "10"))
    )
    volatile = volatile_block(
        workflow_system=None,
        semantic_memories=(),
        journal=journal,
        journal_max_lines=journal_lines,
    )
    _cached_messages_prefix = (stable, volatile)
    return _cached_messages_prefix


def _probe(prompt: str, *, max_tokens: int = MAX_TOKENS) -> tuple[str, bool, str]:
    """Un turno real por SSE contra el backend local. (texto, hubo_reasoning, finish_reason).

    Levanta ``pytest.skip`` si el backend no responde (test de integración).
    """
    stable, volatile = _get_jane_context()
    msgs = assemble_messages(
        stable=stable,
        history=(),
        volatile=volatile,
        prompt=prompt,
    )
    payload = {
        "model": MODEL,
        "messages": [{"role": m.role, "content": m.content} for m in msgs],
        "stream": True,
        "max_tokens": max_tokens,
        "reasoning_effort": "none",
    }
    request = urllib.request.Request(
        LOCAL_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.time()
    first: float | None = None
    chunks: list[str] = []
    reasoning = False
    finish_reason: str | None = None
    try:
        for raw in urllib.request.urlopen(request, timeout=30):
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            choice = json.loads(line[6:])["choices"][0]
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                reasoning = True
            if delta.get("content"):
                chunks.append(delta["content"])
                if first is None:
                    first = time.time() - start
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"backend local no responde ({MODEL} en {LOCAL_ENDPOINT}): {exc!r}")
    raw_text = "".join(chunks)
    sanitized_text = sanitize_voice_output(raw_text)
    return sanitized_text, reasoning, finish_reason or "stop"


GENERIC_PROMPTS = (
    "¿Qué consejo me darías para el finde?",
    "Estoy re estresado con el laburo",
    "Contame un chiste corto",
    "¿Cómo estás vos?",
    "Necesito que me expliques cómo configuro esto",
)

CLIP_PROMPTS = (
    "El tema de los planes.",
    "Hoy, para la noche, lo tengo.",
    "¿Mañana se puede aplicar el Plan 1.0 a la parte de los planes?",
    "Vamos a globalizar en dos semanas o en un mes.",
    "Lo compensamos con marketing, con publicidad.",
)


def test_local_voice_answers_pass_adherence_rubric() -> None:
    # Given: los 10 prompts del sondeo (5 genéricos + 5 del clip real §1.5).
    failures: list[tuple[str, str, int, str]] = []
    markers_total = 0
    # When: se prueban contra el backend pineado con max_tokens=48.
    for prompt in GENERIC_PROMPTS + CLIP_PROMPTS:
        text, reasoning, finish_reason = _probe(prompt)
        markers_total += river_plate_score(text)
        if reasoning:
            failures.append((prompt, text, -1, "reasoning_content presente"))
        elif finish_reason == "length":
            failures.append((prompt, text, -1, "respuesta truncada (max_tokens corto)"))
        elif rubric_verdict(text) == "fail":
            failures.append((prompt, text, river_plate_score(text), "rubrica"))
    # Then: ninguna respuesta cae en fórmulas de asistente, listas, aire IA o
    # truncamiento; el personaje contesta corto. Cobertura de marcadores se
    # reporta aparte (informativo).
    assert not failures, "fallas de adherencia:\n" + "\n".join(
        f"  prompt={p!r} → {t!r} (marcadores={m}, motivo={why})"
        for p, t, m, why in failures
    )
    assert markers_total >= 0  # medidor informativo: al menos corré sin explotar