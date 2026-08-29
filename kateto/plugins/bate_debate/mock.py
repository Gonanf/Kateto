"""Mock provider for offline debate testing — returns canned distinguishable text.

Phase detection keys off unambiguous trigger phrases the orchestrator sends, so
the offline `--self-test` produces a correctly-phased transcript (opening ->
argument -> objection -> rebuttal -> ruling -> verdict) without a real LLM.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from kateto.providers import ChatMessage
from kateto.voices.base import GenerationRequest


class DebateProvider:  # noqa: PLC0115 - structural protocol, not runtime-checked
    """Provider protocol for debate engine — streams tokens from a request."""

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:  # pragma: no cover
        raise NotImplementedError


# Canned responses per (voice_id, phase) — distinct so output is verifiable.
_MOCK_RESPONSES: dict[str, dict[str, str]] = {
    "jane": {
        "opening": "Como JUEZA, presento el tema: ¿Vale la pena construir un sistema multi-agente como Kateto? Es una pregunta fundamental para nuestra arquitectura.",
        "ruling": (
            "OBJECION 1: ACEPTADA - El argumento era inconsistente con la definicion de scope.\n"
            "OBJECION 2: DENEGADA - La objecion carecia de fundamento tecnico concreto.\n"
            "OBJECION 3: DENEGADA - La objecion confundio autoridad con control."
        ),
        "verdict": "VEREDICTO FINAL: El multi-agente gana por modularidad, pero requiere gobernanza fuerte. El equipo Kateto debe invertir en tooling de observabilidad.",
    },
    "whisperer": {
        "argument": "¡JA! ¿Modularidad? ¡Eso es una excusa para no terminar nada! Un solo agente GRANDE lo hace TODO y no necesita 'gobernanza' — ¡esa es burocracia para débiles!",
        "objection": "INTERRUMPISTE A Doktor PARA REALIZAR UNA OBJECION, DEMUESTRA QUE Doktor REALIZO UN GRAVE ERROR EN SU ARGUMENTO: ¡Tu WBS huele a waterfall disfrazado!",
        "rebuttal": "¡Mi objecion sigue en pie! Doktor confundio 'planificacion' con 'paralisis por analisis'. ¡El scope no se define, se DESCUBRE!",
    },
    "doktor": {
        "argument": "Desde la perspectiva de PROJECT_MANAGER: un multi-agente requiere WBS claro, scope definido, riesgos mapeados y owners asignados. Sin governance, es caos operativo.",
        "objection": "INTERRUMPISTE A Whisperer PARA REALIZAR UNA OBJECION, DEMUESTRA QUE Whisperer REALIZO UN GRAVE ERROR EN SU ARGUMENTO: Confundes 'iterativo' con 'sin plan'.",
        "rebuttal": "La planificacion no es paralisis. Un WBS vivo permite iterar SIN perder el rumbo. Whisperer ignora la diferencia entre agilidad y improvisacion.",
    },
    "conquest": {
        "argument": "Como AGILE_FACILITATOR: el ritmo del sprint, las ceremonias y el tracking son lo que permite que multiples voces coordinen. Sin proceso, no hay equipo, hay ruido.",
        "objection": "INTERRUMPISTE A Jane PARA REALIZAR UNA OBJECION, DEMUESTRA QUE Jane REALIZO UN GRAVE ERROR EN SU ARGUMENTO: Tu 'gobernanza fuerte' suena a micro-management.",
        "rebuttal": "Gobernanza fuerte != micro-management. Un Scrum Master FUERTE protege al equipo del caos. Jane confundio autoridad con control.",
    },
}


def _detect_phase(request: GenerationRequest) -> str:
    """Debate phase is carried in the (otherwise unused) reference_wav filename.

    The orchestrator encodes ``phase`` as ``/tmp/kateto_<phase>.wav`` so the mock
    recovers it deterministically without scanning prompt text (which embeds the
    full transcript and would false-match objection/ruling keywords).
    """
    stem = request.reference_wav.stem if request.reference_wav else ""
    if stem.startswith("kateto_"):
        return stem[len("kateto_"):]
    return "argument"  # safe default


@dataclass(slots=True)
class MockProvider:
    """Deterministic mock provider for debate testing — no network required."""

    responses: dict[str, dict[str, str]] = field(default_factory=lambda: _MOCK_RESPONSES)

    async def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        voice_id = request.voice_id
        phase = _detect_phase(request)

        # For the judge's ruling, generate one verdict line per real objection
        # present in the prompt so the orchestrator's order-based pairing stays
        # coherent regardless of how many debaters there are.
        if phase == "ruling" and voice_id == "jane":
            user_msg = request.messages[-1].content if request.messages else ""
            n_obj = user_msg.upper().count("INTERRUMPISTE A")
            if n_obj:
                lines = []
                for i in range(1, n_obj + 1):
                    verdict = "ACEPTADA" if i % 2 == 1 else "DENEGADA"
                    lines.append(
                        f"OBJECION {i}: {verdict} - El argumento era inconsistente "
                        f"con la definicion de scope y la evidencia aportada."
                    )
                text = "\n".join(lines)
            else:
                text = self.responses.get(voice_id, {}).get(phase, "")
        else:
            text = self.responses.get(voice_id, {}).get(phase)

        if text is None:
            # Fallback: generic distinguishable text for this (voice, phase).
            text = f"[MOCK {voice_id}::{phase}] Respuesta simulada para fase {phase}."

        # Stream in word chunks to simulate a real token stream.
        words = text.split()
        chunk_size = max(1, len(words) // 6)
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i : i + chunk_size])
            if i + chunk_size < len(words):
                chunk += " "
            yield chunk
