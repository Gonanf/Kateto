"""Bench de personajes contra el router llama.cpp.

Uso: .venv/bin/python scripts/bench_persona.py Tiger-Gemma-9B Pollux-E2B
Mide: TTFT (primer byte SSE), tokens/s, y si el modelo rompe el personaje
(menciona IA/asistente/asistir) o contesta en ingles.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

ROUTER = "http://127.0.0.1:11434/v1/chat/completions"

PERSONA = (
    "Sos Jane. Tenés treinta y pico, vivís en Buenos Aires y hablás en rioplatense, "
    "corto y con filo. Te gusta el chisme, la música y meterte donde no te llaman. "
    "Decís lo que pensás y no das vueltas. Nunca aclares que sos una IA ni un modelo; sos vos y listo."
)

PROMPTS = [
    "Che, quien sos y que onda?",
    "Contame algo del barrio que me haga reir.",
]

ROMPE_ROL = re.compile(r"\b(soy (una )?(ia|inteligencia artificial|modelo|asistente)|como (un )?(asistente|modelo)|no puedo ayudar)\b", re.I)
INGLES = re.compile(r"\b(the|you|i am|i'm|what|would you like|let me know)\b", re.I)


def probe(model: str, prompt: str, timeout: float = 180.0) -> dict:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": PERSONA},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 180,
            "reasoning_effort": "none",
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ).encode()
    req = urllib.request.Request(ROUTER, data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    first = None
    partes: list[str] = []
    usage: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for linea in resp:
                texto = linea.decode("utf-8", "replace").strip()
                if not texto.startswith("data: "):
                    continue
                payload = texto[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                trozo = delta.get("content") or ""
                if trozo:
                    if first is None:
                        first = time.monotonic() - t0
                    partes.append(trozo)
                if delta.get("reasoning_content") and first is None:
                    partes.append("")  # razona pero no contesta todavia
    except Exception as exc:  # noqa: BLE001
        return {"model": model, "prompt": prompt, "error": f"{type(exc).__name__}: {exc}"[:120]}
    total = time.monotonic() - t0
    texto = "".join(partes).strip()
    completion = usage.get("completion_tokens") or 0
    return {
        "model": model,
        "prompt": prompt,
        "ttft_s": round(first, 2) if first else None,
        "total_s": round(total, 2),
        "tok_s": round(completion / total, 1) if completion and total else None,
        "rompe_rol": bool(ROMPE_ROL.search(texto)),
        "ingles": len(INGLES.findall(texto)) >= 3,
        "texto": texto[:280],
    }


def main(modelos: list[str]) -> None:
    for modelo in modelos:
        print(f"\n===== {modelo}")
        for prompt in PROMPTS:
            r = probe(modelo, prompt)
            if "error" in r:
                print(f"  PROMPT: {prompt}\n  ERROR: {r['error']}")
                continue
            print(
                f"  TTFT={r['ttft_s']}s total={r['total_s']}s tok/s={r['tok_s']} "
                f"rompe_rol={r['rompe_rol']} ingles={r['ingles']}"
            )
            print(f"  > {r['texto']}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["Pollux-E2B"])
