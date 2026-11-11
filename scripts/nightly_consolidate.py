#!/usr/bin/env python3
"""Consolidación "sleep" offline: los turnos del día -> entradas del ledger.

Lee `config_dir/logs/session-*.jsonl` (los `turn_end` que escribe
`executor/conversation_log`), arma un transcript por departamento, le pide al
LLM local sólo hechos declarativos con cita de evidencia, filtra por higiene y
—sólo con `--write`— los guarda en `VoiceMemoryLedger` (tope de 200 entradas,
snapshot/rollback incluidos).

Corre fuera del turno (timer nocturno, celu quieto). Dry-run por defecto:

    uv run python scripts/nightly_consolidate.py --hours 24
    uv run python scripts/nightly_consolidate.py --hours 24 --write --max 5
    uv run python scripts/nightly_consolidate.py --selftest
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hipotenusa.core.config import resolve_config_dir  # noqa: E402
from hipotenusa.voices.ledger import MAX_ENTRIES, MemoryCategory, VoiceMemoryLedger  # noqa: E402

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "Hipotenusa-LFM3-LoRA"
MAX_FACT_CHARS = 400          # igual que el validador del ledger
MAX_EVIDENCE_CHARS = 120      # más corto a propósito: la cita, no el párrafo
# Reglas de higiene: el ledger prohíbe logs de progreso (bug 138 / ledger doc).
_PROGRESS = re.compile(
    r"\b(step|paso|epoch|época|run|corrida)\s*#?\d+|%|"
    r"\d{4}-\d{2}-\d{2}|\bayer\b|\bhoy\b|\bmañana\b|\bminutes?\b|\bminutos?\b",
    re.IGNORECASE,
)
CATEGORIES = {c.value for c in MemoryCategory}

PROMPT = """Sos el consolidador de memoria de un asistente de voz.
Recibís turnos reales de una sesión. Devolvé SOLO un JSON array (sin markdown,
sin texto alrededor) con objetos de esta forma exacta:
[{"category": "facts|relationships|action_patterns", "fact": "...", "evidence": "..."}]

Reglas:
- `fact`: declarativo, atemporal, <=400 caracteres. Nada de logs de progreso
  (ni "step 3", ni fechas, ni porcentajes, ni "hoy/ayer").
- `evidence`: cita textual corta (<=120 caracteres) tomada del transcript.
- `relationships`: quién es quién, jerarquías, preferencias de trato.
- `action_patterns`: cómo resolvemos algo de forma repetible.
- `facts`: todo lo demás que sea cierto y estable.
- Si no hay nada que valga la pena recordar, devolvé [].
- No pienses en voz alta ni expliques: respondé directo con el array, sin ```.
"""


# --- datos -------------------------------------------------------------------


def load_turns(logs_dir: Path, *, hours: float, include_ambiguous: bool = False) -> list[dict[str, Any]]:
    """`turn_end` records dentro de la ventana.

    Por defecto descarta `ambiguous` (sin salida / sin input / multi-voz): eso sirve
    para consolidar memoria, pero NO para el set de EOT, donde `next_transcription`
    llega sin salida por definición. Ahí se pasa include_ambiguous=True.
    """
    since = time.time() - hours * 3600
    turns: list[dict[str, Any]] = []
    for path in sorted(logs_dir.glob("session-*.jsonl")):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < since - 86400:  # archivo viejo: no vale la pena abrirlo
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") != "turn_end":
                    continue
                if rec.get("ambiguous") and not include_ambiguous:
                    continue
                if _epoch(rec.get("ts_end")) < since:
                    continue
                if not (rec.get("input") or rec.get("outputs")):
                    continue
                turns.append(rec)
    turns.sort(key=lambda r: r.get("ts_end") or "")
    return turns


def _epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return 0.0


def voice_dept_map(config_dir: Path) -> dict[str, str]:
    """voice -> dept, desde `voices/<x>/config.toml` (o "fun" si no declara)."""
    mapping: dict[str, str] = {}
    voices_dir = config_dir / "voices"
    if voices_dir.is_dir():
        import tomllib

        for entry in voices_dir.iterdir():
            cfg = entry / "config.toml"
            if not cfg.is_file():
                continue
            try:
                data = tomllib.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            block = data.get("voice", data)
            dept = block.get("dept") if isinstance(block, dict) else None
            mapping[entry.name.casefold()] = str(dept).casefold() if dept else "fun"
    return mapping


def group_by_dept(turns: list[dict[str, Any]], vmap: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in turns:
        voices = {str(o.get("voice", "")).casefold() for o in rec.get("outputs", []) if o.get("voice")}
        depts = {vmap.get(v, "fun") for v in voices} or {"fun"}
        for dept in depts:  # un turno multi-voz entra en cada depto que tocó
            grouped[dept].append(rec)
    return grouped


def build_transcript(turns: list[dict[str, Any]], *, budget: int = 12000) -> str:
    lines: list[str] = []
    used = 0
    for rec in turns:
        outs = [o for o in rec.get("outputs", []) if isinstance(o, dict)]
        said = " ".join(str(outs[-1].get("text", "")).split())[:300] if outs else ""
        user = " ".join(str(rec.get("input", "")).split())[:300]
        voices = ",".join(str(o.get("voice", "")) for o in outs)
        chunk = f"USUARIO: {user}\nASISTENTE ({voices}): {said}"
        if used + len(chunk) > budget:
            break
        lines.append(chunk)
        used += len(chunk)
    return "\n\n".join(lines)


# --- extracción --------------------------------------------------------------


def call_llm(transcript: str, *, endpoint: str, model: str, api_key: str, timeout: float = 180.0) -> str:
    body = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 1800,  # los modelos con razonamiento queman presupuesto antes del JSON
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"Turnos:\n\n{transcript}"},
        ],
    }
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    return payload["choices"][0]["message"]["content"]


def parse_candidates(raw: str) -> list[dict[str, str]]:
    """JSON array tolerante: acepta texto alrededor y objetos sueltos."""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append({k: str(v) for k, v in item.items() if isinstance(v, (str, int, float))})
    return out


def hygiene(candidate: dict[str, str]) -> str | None:
    """None = pasa. Devuelve el motivo del rechazo."""
    fact = " ".join(candidate.get("fact", "").split())
    evidence = " ".join(candidate.get("evidence", "").split())
    if candidate.get("category") not in CATEGORIES:
        return f"categoría inválida: {candidate.get('category')!r}"
    if not fact:
        return "sin fact"
    if len(fact) > MAX_FACT_CHARS:
        return f"fact demasiado largo ({len(fact)} > {MAX_FACT_CHARS})"
    if not evidence:
        return "sin evidence (el ledger la exige)"
    if len(evidence) > MAX_EVIDENCE_CHARS * 4:
        return f"evidence desmesurada ({len(evidence)})"
    if _PROGRESS.search(fact):
        return "parece log de progreso (fecha/número/porcentaje)"
    return None


def dedupe(
    candidates: list[dict[str, str]], existing: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], int]:
    """Saca duplicados contra el ledger y entre sí. Devuelve (nuevos, descartados)."""
    seen = {_norm(str(e.get("fact", ""))) for e in existing}
    new: list[dict[str, str]] = []
    dropped = 0
    for cand in candidates:
        key = _norm(cand.get("fact", ""))
        if not key or key in seen:
            dropped += 1
            continue
        seen.add(key)
        new.append(cand)
    return new, dropped


def _norm(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" .;:!?")


# --- main --------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    config_dir = Path(args.config_dir).expanduser() if args.config_dir else resolve_config_dir()
    logs_dir = config_dir / "logs"

    turns = load_turns(logs_dir, hours=args.hours)
    if not turns:
        print(f"sleep: sin turnos en las últimas {args.hours}h ({logs_dir})")
        return 0
    grouped = group_by_dept(turns, voice_dept_map(config_dir))
    print(f"sleep: {len(turns)} turnos en {', '.join(f'{d}={len(t)}' for d, t in grouped.items())}")

    writes = 0
    for dept, dept_turns in sorted(grouped.items()):
        ledger = VoiceMemoryLedger.for_dept(config_dir=config_dir, dept=dept)
        existing = ledger.entries()
        room = MAX_ENTRIES - len(existing)
        transcript = build_transcript(dept_turns)
        try:
            raw = call_llm(transcript, endpoint=args.endpoint, model=args.model, api_key=args.api_key)
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as err:
            print(f"[{dept}] LLM no respondió: {type(err).__name__}: {err}")
            continue

        if args.show_raw:
            print(f"[{dept}] raw: {raw[:600]!r}")
        cands = parse_candidates(raw)
        new, dropped = dedupe(cands, existing)
        print(f"[{dept}] candidatos={len(cands)} nuevos={len(new)} duplicados={dropped} room={room}")
        for cand in new:
            why = hygiene(cand)
            if why:
                print(f"  ✗ {why}: {cand.get('fact', '')[:90]}")
                continue
            if writes >= args.max:
                print(f"  … tope --max {args.max} alcanzado, no escribo")
                break
            if room - writes <= 0:
                print(f"  ✗ ledger lleno ({MAX_ENTRIES}), no escribo (evito desalojar viejas)")
                break
            if not args.write:
                print(f"  ✓ [{cand['category']}] {cand['fact'][:110]}  ⟵ {cand['evidence'][:60]}")
                writes += 1
                continue
            result = await ledger.refine(
                fact=cand["fact"], category=cand["category"], evidence=cand["evidence"]
            )
            writes += 1
            print(f"  + [{result['category']}] {result['action']}: {str(result['fact'])[:90]}")
    if not args.write:
        print(f"\n(dry-run) {writes} candidatos listos. Escribir: --write (máx {args.max}/depto)")
    return 0


def selftest() -> int:
    """Check runnable sin red ni disco real: parseo, higiene, dedupe, transcript."""
    import tempfile

    raw = 'bla [{"category":"facts","fact":"Rodrigo prefiere respuestas cortas.","evidence":"cortas ya"},' \
          '{"category":"progress","fact":"step 3 terminó","evidence":"x"},' \
          '{"category":"facts","fact":"Rodrigo prefiere respuestas cortas.","evidence":"dup"}] blu'
    cands = parse_candidates(raw)
    assert len(cands) == 3, cands
    assert hygiene(cands[0]) is None, hygiene(cands[0])
    assert hygiene(cands[1]) == "categoría inválida: 'progress'"
    assert hygiene({"category": "facts", "fact": "x", "evidence": ""}) == "sin evidence (el ledger la exige)"
    assert hygiene({"category": "facts", "fact": "hoy desplegamos a las 2026-11-10", "evidence": "e"}) == \
        "parece log de progreso (fecha/número/porcentaje)"

    existing = [{"fact": "Rodrigo prefiere respuestas cortas."}]
    new, dropped = dedupe(cands, existing)
    # dedupe corre ANTES de higiene: sobrevive el candidato único aunque después lo filtre hygiene.
    assert [c["fact"] for c in new] == ["step 3 terminó"] and dropped == 2, (new, dropped)
    assert hygiene(new[0]) == "categoría inválida: 'progress'"  # categoría se valida primero
    new2, dropped2 = dedupe([{"category": "facts", "fact": "Otra cosa.", "evidence": "e"}], existing)
    assert len(new2) == 1 and dropped2 == 0

    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp) / "logs"
        logs.mkdir()
        now = datetime.now().astimezone()
        rec = {"event": "turn_end", "ts_end": now.isoformat(), "input": "hola",
               "outputs": [{"voice": "dionisio", "text": "qué tal"}], "ambiguous": False}
        amb = {"event": "turn_end", "ts_end": now.isoformat(), "input": "x",
               "outputs": [], "ambiguous": True}
        old = {"event": "turn_end", "ts_end": (now - timedelta(days=3)).isoformat(), "input": "viejo",
               "outputs": [{"voice": "dionisio", "text": "y"}], "ambiguous": False}
        (logs / f"session-{now:%Y-%m-%d}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (rec, amb, old)) + "\n", encoding="utf-8")
        turns = load_turns(logs, hours=24)
        assert len(turns) == 1, turns
        assert "USUARIO: hola" in build_transcript(turns)
        vmap = voice_dept_map(Path(tmp))
        grouped = group_by_dept(turns, vmap)
        assert list(grouped) == ["fun"], grouped
    print("selftest ok: parseo, higiene, dedupe, ventana y agrupación")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--max", type=int, default=5, help="tope de escrituras por depto")
    ap.add_argument("--write", action="store_true", help="sin esto es dry-run")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--api-key", default="none")
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--show-raw", action="store_true", help="imprime la respuesta cruda del LLM")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
