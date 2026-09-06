"""
División de textos largos en chunks coherentes.

TODO / criterio a revisar:
 - Actualmente split por: \n\n (doble salto), bullets (•, -, *), listas numeradas (1. 2.), y "---" separador.
 - Esto puede sobre-splitear si el texto es una sola respuesta larga con párrafos intencionales.
 - Alternativas a evaluar: no splitear si el texto tiene < N bullets pero es 1 solo chiste largo;
   usar LLM para segmentar; o usar longitud mínima/máxima dinámica según dataset.
 - Revisar con el usuario: ¿queremos preservar párrafos de una misma respuesta o siempre atomizar?
"""
from __future__ import annotations

import re
import logging

log = logging.getLogger("dataset_filter.splitter")

# Patrones de split
_SPLIT_RE = re.compile(
    r"""
    (?:\n\s*\n)                      # doble salto
    |(?:\n\s*(?:[•\-*]|\d+[.)])\s+)    # bullet al inicio de línea
    |(?:\n\s*---+\s*\n)               # separador ---
    """,
    re.VERBOSE,
)

# Bullets inline " - texto - texto" no se splitea, solo bullets al inicio de línea
_BULLET_LINE_RE = re.compile(r"^\s*(?:[•\-*]|\d+[.)])\s+", re.M)


def split_long_text(
    text: str,
    *,
    min_chars: int = 10,
    max_chars: int = 800,
    max_chunks: int = 20,
) -> list[str]:
    """
    Si el texto parece contener múltiples items, lo splitea en respuestas individuales.
    Cada chunk debe ser coherente por sí solo. Filtra basura < min_chars.
    Si un chunk supera max_chars, lo trunca (no lo re-splitea por palabras para no romper coherencia).
    """
    t = (text or "").strip()
    if not t:
        return []
    # Heurística: solo splitear si hay señales de multi-item
    has_double_nl = "\n\n" in t
    has_bullets = bool(_BULLET_LINE_RE.search(t))
    # si es texto corto sin señales, devolver 1 chunk
    if not has_double_nl and not has_bullets and len(t) < max_chars * 1.2:
        return [t] if len(t) >= min_chars else []

    # split
    parts = _SPLIT_RE.split(t)
    # fallback: si el regex no spliteó pero hay \n\n, split manual
    if len(parts) == 1 and has_double_nl:
        parts = [p.strip() for p in t.split("\n\n")]

    chunks: list[str] = []
    for p in parts:
        # limpiar bullet prefix residual
        p = re.sub(r"^\s*(?:[•\-*]|\d+[.)])\s+", "", p.strip())
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < min_chars:
            continue
        if len(p) > max_chars:
            # truncar manteniendo coherencia: cortar en último punto antes de max
            cut = p.rfind(".", 0, max_chars)
            if cut > min_chars:
                p = p[: cut + 1].strip()
            else:
                p = p[:max_chars].strip()
        chunks.append(p)
        if len(chunks) >= max_chunks:
            break

    # Si el split produjo basura (ej 0 chunks), devolver original si cumple min
    if not chunks and len(t) >= min_chars:
        trunc = t[:max_chars] if len(t) > max_chars else t
        return [trunc]
    return chunks
