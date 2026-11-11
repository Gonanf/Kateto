#!/usr/bin/env python3
"""Probe del bucle: Propose -> Probe -> Compose (Harness², arXiv 2610.14224).

Corre la MISMA tarea contra dos variantes de harness (antes/después de una
edición de SOUL, skill o prompt), guarda las dos salidas lado a lado y, con
`--record`, deja la evidencia en `improvement-harness.md`. No puntúa: el
contraste lo firmás vos (o el reflector). Sin set congelado no hay veredicto.

    uv run python scripts/harness_probe.py --task "..." --before SOUL.md --after SOUL-nuevo.md
    uv run python scripts/harness_probe.py --task "..." --before X --after Y --record
    uv run python scripts/harness_probe.py --task "..." --before X --after Y --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "Hipotenusa-LFM3-LoRA"


def ask(task: str, system: str, *, endpoint: str, model: str, api_key: str) -> str:
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ],
    }
    req = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"].strip()


def record(path: Path, *, task: str, before: Path, after: Path, out: dict[str, str]) -> None:
    """Una entrada = una edición probada + su evidencia. Se agrega al final."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    block = [
        f"\n## {stamp} · {after.name}",
        "",
        f"- tarea: {task}",
        f"- antes: `{before}`",
        f"- después: `{after}`",
        "",
        "**antes**",
        "",
        "```",
        out["before"][:900],
        "```",
        "",
        "**después**",
        "",
        "```",
        out["after"][:900],
        "```",
        "",
        "- veredicto: _(pendiente: adoptada / descartada; qué contrastó)_",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True)
    ap.add_argument("--before", required=True, help="archivo con el harness actual")
    ap.add_argument("--after", required=True, help="archivo con la edición propuesta")
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--api-key", default="none")
    ap.add_argument("--out", default="out/harness-probe")
    ap.add_argument("--harness", default="improvement-harness.md")
    ap.add_argument("--record", action="store_true", help="agregar la evidencia al harness")
    ap.add_argument("--dry-run", action="store_true", help="mostrar prompts y salir")
    args = ap.parse_args()

    before_path, after_path = Path(args.before).expanduser(), Path(args.after).expanduser()
    before = before_path.read_text(encoding="utf-8")
    after = after_path.read_text(encoding="utf-8")

    if args.dry_run:
        for label, text in (("antes", before), ("después", after)):
            print(f"--- {label} ({len(text)} chars) ---")
            print(text[:500])
            print()
        print(f"tarea: {args.task}")
        return 0

    out: dict[str, str] = {}
    for label, system in (("before", before), ("after", after)):
        t0 = time.time()
        try:
            out[label] = ask(args.task, system, endpoint=args.endpoint, model=args.model, api_key=args.api_key)
        except Exception as err:  # red o modelo caído: no inventamos salida
            print(f"{label}: FALLÓ {type(err).__name__}: {err}")
            return 1
        print(f"--- {label} ({time.time() - t0:.1f}s) ---\n{out[label]}\n")

    run_dir = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "before.txt").write_text(out["before"], encoding="utf-8")
    (run_dir / "after.txt").write_text(out["after"], encoding="utf-8")
    (run_dir / "task.txt").write_text(args.task, encoding="utf-8")
    print(f"guardado en {run_dir}")

    if args.record:
        record(Path(args.harness), task=args.task, before=before_path, after=after_path, out=out)
        print(f"evidencia agregada a {args.harness} (veredicto queda pendiente)")
    if out["before"] == out["after"]:
        print("aviso: salidas idénticas — la edición no movió nada, no la adoptes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
