#!/usr/bin/env python3
"""E1: set de eval de EOT derivado de los logs reales (`closed_by`).

Sin este set no hay forma de saber si el gate acierta en *esta* distribución: los
F1 del repo hermano (0.645 wait / 0.841 no_response) son de su propio test set.

Etiquetas (de `turn_end` / `closed_by`):
  voice_idle            -> la voz terminó y quedó idle: el turno estaba COMPLETO  -> wait=0
  next_transcription    -> el usuario siguió hablando antes del idle: INCOMPLETO   -> wait=1
  interrupt             -> cortó la respuesta (input completo, salida truncada)    -> se descarta
  (todo lo demás)        -> se descarta

    uv run python scripts/qa/build_eot_eval.py                  # construir
    uv run python scripts/qa/build_eot_eval.py --score          # + medir el gate real
    uv run python scripts/qa/build_eot_eval.py --selftest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hipotenusa.core.config import resolve_config_dir  # noqa: E402
from scripts.nightly_consolidate import _epoch, load_turns  # noqa: E402

EOT2_DIR = Path("/run/media/chaos/secundario/proyectos/kateto-eot2")
EOT2_CLI = EOT2_DIR / "clasificador_hibrido.py"
EOT2_PY = EOT2_DIR / ".venv/bin/python"

LABELS = {"voice_idle": 0, "next_transcription": 1}  # wait=1 -> el turno seguía
DROPPED = {"interrupt"}


def build_pairs(turns: list[dict]) -> list[dict]:
    pairs: list[dict] = []
    for rec in turns:
        closed_by = str(rec.get("closed_by") or "")
        if closed_by in DROPPED or closed_by not in LABELS:
            continue
        text = " ".join(str(rec.get("input") or "").split())
        if len(text) < 2:
            continue
        pairs.append({
            "text": text,
            "wait": LABELS[closed_by],
            "closed_by": closed_by,
            "ts_end": rec.get("ts_end"),
            "voices": [o.get("voice") for o in rec.get("outputs", []) if isinstance(o, dict)],
        })
    return pairs


def f1(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def score(pairs: list[dict], predict) -> dict:
    """predict: text -> {"wait": bool, "no_response": bool}."""
    tp = fp = fn = 0
    no_resp_hits = Counter()
    for pair in pairs:
        got = predict(pair["text"])
        if pair["wait"] == 1:
            if got.get("wait"):
                tp += 1
            else:
                fn += 1
        elif got.get("wait"):
            fp += 1
        if got.get("no_response"):
            no_resp_hits[pair["wait"]] += 1
    return {
        "n": len(pairs),
        "wait_f1": round(f1(tp, fp, fn), 4),
        "tp": tp, "fp": fp, "fn": fn,
        "no_response_en_wait1": no_resp_hits[1],
        "no_response_en_wait0": no_resp_hits[0],
    }


def make_child_predict():
    """Predictor real: el mismo proceso hijo que usa el runtime (EOT2 venv)."""
    if not (EOT2_CLI.is_file() and EOT2_PY.is_file()):
        raise SystemExit(f"falta el repo hermano: {EOT2_CLI} / {EOT2_PY}")
    proc = subprocess.Popen(
        [str(EOT2_PY), str(EOT2_CLI)], cwd=str(EOT2_DIR),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
    )

    def predict(text: str) -> dict:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(" ".join(text.split()) + "\n")
        proc.stdin.flush()
        payload = json.loads(proc.stdout.readline())
        return {
            "wait": bool(payload.get("wait", {}).get("decision")),
            "no_response": bool(payload.get("no_response", {}).get("decision")),
        }

    return predict, proc


def selftest() -> int:
    turns = [
        {"event": "turn_end", "closed_by": "voice_idle", "input": "hola che", "outputs": [{"voice": "dionisio"}]},
        {"event": "turn_end", "closed_by": "next_transcription", "input": "quiero que", "outputs": []},
        {"event": "turn_end", "closed_by": "interrupt", "input": "dale", "outputs": []},
        {"event": "turn_end", "closed_by": "voice_idle", "input": "  ", "outputs": []},
        {"event": "turn_end", "closed_by": None, "input": "x", "outputs": []},
    ]
    pairs = build_pairs(turns)
    assert [p["wait"] for p in pairs] == [0, 1], pairs
    assert pairs[0]["closed_by"] == "voice_idle" and pairs[1]["text"] == "quiero que"

    # predictor perfecto -> F1 1.0; predictor que siempre responde -> F1 0
    perfect = lambda t: {"wait": "quiero" in t, "no_response": False}  # noqa: E731
    res = score(pairs, perfect)
    assert res["wait_f1"] == 1.0, res
    lazy = lambda t: {"wait": False, "no_response": False}  # noqa: E731
    res2 = score(pairs, lazy)
    assert res2["wait_f1"] == 0.0 and res2["fn"] == 1, res2
    noisy = lambda t: {"wait": True, "no_response": False}  # noqa: E731
    res3 = score(pairs, noisy)
    assert res3["wait_f1"] == round(2 * 0.5 * 1.0 / 1.5, 4), res3  # precision .5, recall 1
    print("selftest ok: etiquetas por closed_by, descartes, F1 wait")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=24 * 30)
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--out", default=None, help="default: out/eot-eval-<YYYY-MM>.jsonl")
    ap.add_argument("--score", action="store_true", help="corre el gate real sobre el set")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    config_dir = Path(args.config_dir).expanduser() if args.config_dir else resolve_config_dir()
    # include_ambiguous: los turnos WAIT (next_transcription) llegan sin salida
    turns = load_turns(config_dir / "logs", hours=args.hours, include_ambiguous=True)
    pairs = build_pairs(turns)
    if not pairs:
        print(f"sin pares en {config_dir / 'logs'} (turnos leídos: {len(turns)})")
        return 1

    month = str(pairs[-1]["ts_end"])[:7] if pairs[-1]["ts_end"] else "sin-fecha"
    out = Path(args.out) if args.out else Path("out") / f"eot-eval-{month}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, ensure_ascii=False) + "\n")

    balance = Counter(p["closed_by"] for p in pairs)
    print(f"pares: {len(pairs)}  ({dict(balance)})  -> {out}")
    if len(pairs) < 200:
        print(f"aviso: menos de 200 pares ({len(pairs)}); el criterio de E1 pide >=200")

    if args.score:
        predict, proc = make_child_predict()
        try:
            res = score(pairs, predict)
        finally:
            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=10)
        print(f"gate real: wait_f1={res['wait_f1']} tp={res['tp']} fp={res['fp']} fn={res['fn']} "
              f"| no_response en wait1={res['no_response_en_wait1']} wait0={res['no_response_en_wait0']}")
        print("referencia del repo hermano: wait F1 0.6452, no_response F1 0.8412")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
