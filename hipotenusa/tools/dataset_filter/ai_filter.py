"""
Filtro de textos generados por IA — heurística + hook clasificador binario.

Heurística (rápida, sin modelo):
 - em dashes (—), en dash (–) excesivos, bullets perfectos
 - frases típicas LLM: "As an AI", "En conclusión", "Es importante recordar", etc.
 - verbosidad / estructura demasiado prolija para chat argento
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass

log = logging.getLogger("dataset_filter.ai_filter")

# Patrones típicos IA (ES + EN)
AI_PHRASES = [
    r"as an ai\b",
    r"as a language model",
    r"i am an ai",
    r"soy una ia\b",
    r"soy un modelo de lenguaje",
    r"en conclusión[, ]",
    r"en resumen[, ]",
    r"es importante (recordar|destacar|tener en cuenta|señalar)",
    r"espero que esta (respuesta|información) te (sea útil|ayude)",
    r"si tenés alguna (otra )?pregunta",
    r"no dudes en preguntar",
    r"aquí tienes (algunas|una lista)",
    r"a continuación (te )?(presento|encontrarás)",
    r"\bdelve\b",
    r"\btapestry\b",
    r"it's important to note",
    r"in conclusion[, ]",
    r"overall[, ]",
]
AI_RE = re.compile("|".join(AI_PHRASES), re.I)

# emdash / endash — la IA los usa mucho; el humano casi nunca en chat
EMDASH_RE = re.compile(r"[—–]")

# Bullets / listas demasiado perfectas
BULLET_RE = re.compile(r"(^|\n)\s*([•\-*]|\d+\.)\s+\S+", re.M)

# Texto con múltiples párrafos ultra-formales (heurística longitud + conectores)
FORMAL_CONNS = re.compile(r"\b(además|asimismo|por consiguiente|no obstante|sin embargo|por lo tanto)\b", re.I)


@dataclass
class AIFilterResult:
    is_ai_like: bool
    score: float  # 0..1
    reasons: list[str]


def heuristic_ai_score(text: str) -> AIFilterResult:
    reasons: list[str] = []
    score = 0.0
    t = text.strip()
    if not t:
        return AIFilterResult(False, 0.0, ["empty"])

    # emdash
    em_count = len(EMDASH_RE.findall(t))
    if em_count >= 1:
        # un solo emdash ya es sospechoso en argento coloquial, 2+ casi seguro IA
        s = 0.35 if em_count == 1 else 0.7
        score += s
        reasons.append(f"emdash x{em_count}")

    # frases IA
    if AI_RE.search(t):
        score += 0.6
        reasons.append("ai_phrase")

    # bullets/listas + formalidad + longitud excesiva
    bullets = len(BULLET_RE.findall(t))
    if bullets >= 3:
        score += 0.4
        reasons.append(f"bullets x{bullets}")
    if len(t) > 800 and FORMAL_CONNS.search(t):
        score += 0.3
        reasons.append("verbose_formal")

    # mayúsculas perfectas + sin lunfardo (proxy inverso: si tiene lunfardo, baja score)
    lunfardo = re.search(r"\b(che|boludo|posta|chabón|pibe|laburo|guita|quilombo|morfar|bondi)\b", t, re.I)
    if lunfardo and score > 0:
        score = max(0, score - 0.2)
        reasons.append("lunfardo_-0.2")

    score = min(1.0, score)
    return AIFilterResult(score >= 0.5, score, reasons)


# Hook opcional: clasificador binario IA vs humano (placeholder)
class AIBinaryClassifierHook:
    """
    Placeholder para modelo binario IA vs humano.
    Implementá .predict(texts)->list[float] con tu checkpoint y pasalo a is_ai().
    Si no hay modelo, usa solo heurística.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path
        self._loaded = False
        if model_path:
            log.warning("AIBinaryClassifierHook: model_path=%s — TODO cargar checkpoint real", model_path)
            # TODO: cargar ONNX/HF binario y setear _loaded=True

    def predict(self, texts: list[str]) -> list[float] | None:
        if not self._loaded:
            return None
        # TODO: return probs 0..1
        return None


_binary_hook: AIBinaryClassifierHook | None = None


def set_binary_classifier(hook: AIBinaryClassifierHook) -> None:
    global _binary_hook
    _binary_hook = hook


def is_ai_like(text: str, threshold: float = 0.5) -> AIFilterResult:
    """Heurística + hook opcional (si hay modelo, promedia)."""
    h = heuristic_ai_score(text)
    if _binary_hook is not None:
        probs = _binary_hook.predict([text])
        if probs is not None:
            p = float(probs[0])
            # promedio simple heurística+modelo
            combined = 0.5 * h.score + 0.5 * p
            reasons = h.reasons + [f"model={p:.2f}"]
            return AIFilterResult(combined >= threshold, combined, reasons)
    return AIFilterResult(h.is_ai_like and h.score >= threshold, h.score, h.reasons)
