"""PIN del razonamiento — cable de hoy (todas las voces): ``reasoning_effort=none``.

Si un knob futuro deja de mandar "none" (o el backend vuelve a emitir
``reasoning_content``), estos tests lo cazan.

- Asserts unitarios de :func:`resolve_reasoning_effort` (determinista, corre
  siempre). El cableado del wire (``extra_body``) ya lo cubre
  test_voice_llm_params.py.
- Sondeo real acotado contra el backend local (:11434, KatetoGemma) con
  ``max_tokens=48``: verifica TTFT en régimen y ausencia de
  ``reasoning_content``. Test de integración: se saltea si el backend no
  responde.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import pytest

from kateto.voices.base import resolve_reasoning_effort

LOCAL_ENDPOINT = "http://localhost:11434/v1/chat/completions"
MODEL = "KatetoGemma"
MAX_TOKENS = 48
TTFT_BUDGET_S = 2.5


def test_thinking_false_implies_reasoning_none() -> None:
    assert resolve_reasoning_effort(None, False) == "none"


def test_explicit_reasoning_wins_over_thinking() -> None:
    assert resolve_reasoning_effort("low", False) == "low"
    assert resolve_reasoning_effort("none", True) == "none"


def test_thinking_true_or_unset_sends_nothing() -> None:
    assert resolve_reasoning_effort(None, True) is None
    assert resolve_reasoning_effort(None, None) is None


def _probe(prompt: str, *, max_tokens: int = MAX_TOKENS) -> tuple[float, str, bool]:
    """Un turno real por SSE contra el backend local. (ttft_s, texto, hubo_reasoning).

    Levanta ``pytest.skip`` si el backend no responde (test de integración).
    """
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
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
    try:
        for raw in urllib.request.urlopen(request, timeout=30):
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            delta = json.loads(line[6:])["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                reasoning = True
            if delta.get("content"):
                chunks.append(delta["content"])
                if first is None:
                    first = time.time() - start
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"backend local no responde ({MODEL} en {LOCAL_ENDPOINT}): {exc!r}")
    return (first if first is not None else time.time() - start), "".join(chunks), reasoning


def test_local_pin_probe_fast_and_without_reasoning() -> None:
    # Given: el backend con el cable pineado (warm-up aparte para no medir carga).
    _probe("calentando el cache del modelo")
    # When: un turno corto real con reasoning_effort=none.
    ttft, text, reasoning = _probe("¿Qué consejo me darías para el finde?")
    # Then: TTFT dentro del presupuesto, sin razonamiento oculto, respuesta no vacía.
    assert ttft < TTFT_BUDGET_S, f"TTFT {ttft:.2f}s >= presupuesto {TTFT_BUDGET_S}s"
    assert not reasoning, "llegó reasoning_content con reasoning_effort=none en el cable"
    assert text.strip(), "respuesta vacía"