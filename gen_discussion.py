"""Discusion tipo panel usando las voces REALES de Kateto.

Reusa kateto.voices.factory._PROFILES (perfiles reales con sus roles) y
kateto.voices.base.OpenAICompatibleProvider (provider LLM real, :11434).
Jane actua de moderadora/jueza: plantea el tema, pide opinion a las otras
voces, y cierra con veredicto. El texto se vuelca a .md (no a TTS).
Uso: uv run python gen_discussion.py ["tema opcional"]
"""
from __future__ import annotations

import asyncio
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from kateto.providers import ChatMessage
from kateto.voices.base import GenerationRequest, OpenAICompatibleProvider
from kateto.voices.factory import _PROFILES

import os
from kateto.core.config import load_config

ENDPOINT = "http://localhost:11434/v1"
MODEL = "Kateto"
try:
    _cfg = load_config()
    _vllm = _cfg.settings.plugin.get("voice_llm") if _cfg.settings.plugin else None
    if _vllm is not None:
        ENDPOINT = getattr(_vllm, "endpoint", None) or (isinstance(_vllm, dict) and _vllm.get("endpoint")) or ENDPOINT
        MODEL = getattr(_vllm, "model", None) or (isinstance(_vllm, dict) and _vllm.get("model")) or MODEL
except Exception:
    pass
ENDPOINT = os.environ.get("KATETO_LLM_ENDPOINT") or ENDPOINT
MODEL = os.environ.get("KATETO_LLM_MODEL") or MODEL

_SPEECH_CONSTRAINT = (
    " You are a voice assistant in a live conversation. Never use symbols, bullet"
    " points, markdown, or multi-line formatted text. Speak in short, natural"
    " sentences as if talking out loud. No lists, no headers, no dashes."
)
_PANEL = ["whisperer", "doktor", "conquest"]  # voces que opinan; Jane modera/juzga
_TOPICS = [
    "Vale la pena construir un sistema multi-agente como Kateto en vez de un solo agente grande?",
    "El streaming de respuestas en vivo mejora la experiencia o solo agrega latencia y bugs?",
    "Las voces de un asistente deberian tener personalidades opuestas o todas serviles?",
    "El hot-reload 'aunque rompa' es buena idea para un sistema de voz en produccion?",
    "Planificar con metodologias agiles aporta algo a un proyecto de un solo desarrollador?",
]


def _doc_prompt(voice_id: str) -> str:
    base = _PROFILES[voice_id].system_prompt
    if base.endswith(_SPEECH_CONSTRAINT):
        base = base[: -len(_SPEECH_CONSTRAINT)]
    return (
        base + " Estas en una DISCUSION ESCRITA entre las voces del equipo Kateto, no"
        " hablando por voz. Responde en ESPANOL, parrafos libres. Manten tu rol."
    )


def _clean(name: str, text: str) -> str:
    # el modelo se autoprefija "Nombre: ..."; lo saco porque el .md ya lo etiqueta.
    return re.sub(rf"^\s*{re.escape(name)}\s*[:\-]\s*", "", text, flags=re.I).strip()


async def speak(voice_id: str, user: str, *, timeout: float = 120) -> str:
    provider = OpenAICompatibleProvider(model=MODEL, endpoint=ENDPOINT, api_key="sk-no")
    msgs = (
        ChatMessage(role="system", content=_doc_prompt(voice_id)),
        ChatMessage(role="user", content=user),
    )
    req = GenerationRequest(voice_id=voice_id, reference_wav=None, messages=msgs)

    async def _collect() -> str:
        out = []
        async for tok in provider.stream(req):
            out.append(tok)
        return "".join(out).strip()

    try:
        text = await asyncio.wait_for(_collect(), timeout=timeout)
        return _clean(_PROFILES[voice_id].display_name, text)
    except asyncio.TimeoutError:
        return f"[VOZ CORTADA POR TIMEOUT]"
    except Exception as e:  # noqa: BLE001
        return f"[ERROR {type(e).__name__}: {e}]"


async def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else random.choice(_TOPICS)
    jane = _PROFILES["jane"].display_name

    # 1) Jane modera: plantea el tema al panel.
    framing = await speak(
        "jane",
        f"Eres la MODERADORA de un panel de expertos del equipo Kateto. Presenta este"
        f" tema al panel y formula la pregunta central que deben debatir:\n\nTEMA: {topic}",
    )
    # 2) El panel opina, cada voz ve el planteamiento de Jane.
    opinions: dict[str, str] = {}
    for vid in _PANEL:
        opinions[vid] = await speak(
            vid,
            f"La moderadora Jane planteo al panel:\n\"{framing}\"\n\nDa tu OPINION como"
            f" {_PROFILES[vid].display_name} ({_PROFILES[vid].role.value}). 2 a 4 oraciones.",
        )
    # 3) Jane jueza: sintetiza y veredicto.
    panel_block = "\n".join(f"- {_PROFILES[v].display_name}: {t}" for v, t in opinions.items())
    verdict = await speak(
        "jane",
        f"Como JUEZA del panel, lee las opiniones y dicta veredicto:\n{panel_block}\n\n"
        f"Sintetiza lo mas fuerte de cada postura, senala el argumento mas solido y"
        f" cierra con una conclusion. 3 a 5 oraciones.",
    )

    out = Path(__file__).parent / "discusion_kateto.md"
    md = [
        f"# Panel Kateto: {topic}\n",
        f"_Generado {datetime.now():%Y-%m-%d %H:%M} con las voces reales de Kateto"
        f" ({ENDPOINT}, modelo `{MODEL}`). Jane modera y juzga; panel ="
        f" {', '.join(_PROFILES[v].display_name for v in _PANEL)}._\n",
        f"**Tema:** {topic}\n---\n",
        f"## Moderadora (Jane) plantea\n\n{framing}\n",
    ]
    for v, t in opinions.items():
        md.append(f"## {_PROFILES[v].display_name} opina\n\n{t}\n")
    md.append(f"## Veredicto de Jane (jueza)\n\n{verdict}\n")
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"ESCRITO: {out}")


if __name__ == "__main__":
    asyncio.run(main())
