"""Mide PREFILL (prompt eval) contra el router, con un prompt del tamano real de un turno.

Uso: .venv/bin/python scripts/bench_prefill.py Pollux-E2B Tiger-Q2
Decode no entra en la cuenta: max_tokens=1. Lo que importa es prompt_per_second.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

ROUTER = "http://127.0.0.1:11434/v1/chat/completions"

# ~1.6k tokens de relleno: un turno de voz real (persona + historial + prompt).
RELLENO = (
    "Che, mirá, te cuento que en el barrio pasan cosas todo el tiempo y una se entera de todo. "
    "La vecina del primero se peleo con el del tercero por una maceta, el kiosquero cambio de horario, "
    "y el pibe del fondo se compro una moto que hace un ruido terrible a las tres de la mañana. "
) * 60

PREGUNTA = "Contame algo del barrio que me haga reir."


def medir(modelo: str, timeout: float = 300.0) -> dict:
    body = json.dumps(
        {
            "model": modelo,
            "messages": [
                {"role": "system", "content": "Sos Jane, rioplatense, corto y con filo."},
                {"role": "user", "content": RELLENO + "\n\n" + PREGUNTA},
            ],
            "max_tokens": 1,
            "reasoning_effort": "none",
        }
    ).encode()
    req = urllib.request.Request(ROUTER, data=body, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        return {"model": modelo, "error": f"{type(exc).__name__}: {exc}"[:120]}
    pared = time.monotonic() - t0
    t = data.get("timings") or {}
    return {
        "model": modelo,
        "prompt_tokens": t.get("prompt_n"),
        "prefill_tok_s": round(t.get("prompt_per_second") or 0, 1),
        "ttft_pared_s": round(pared, 2),
    }


def main(modelos: list[str]) -> None:
    for modelo in modelos:
        r = medir(modelo)
        if "error" in r:
            print(f"{modelo}: ERROR {r['error']}")
            continue
        print(
            f"{modelo}: {r['prompt_tokens']} tok de prompt, "
            f"prefill {r['prefill_tok_s']} tok/s, pared {r['ttft_pared_s']}s"
        )


if __name__ == "__main__":
    main(sys.argv[1:] or ["Pollux-E2B"])
