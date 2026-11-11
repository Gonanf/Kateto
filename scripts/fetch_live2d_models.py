#!/usr/bin/env python3
"""Baja los modelos Live2D del elenco de entrevista a `assets/live2d/`.

Los modelos de muestra vienen de Live2D/CubismWebSamples (licencia de material gratuito de Live2D: uso
libre, no comercial). No se versionan en git por peso; este script los reconstruye.

Uso: python3 scripts/fetch_live2d_models.py [--force]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEST = REPO / "assets/live2d"
CDN = "https://cdn.jsdelivr.net/gh/Live2D/CubismWebSamples@develop/Samples/Resources"
MODELS = {
    "hiyori": f"{CDN}/Hiyori/Hiyori.model3.json",
    "mao": f"{CDN}/Mao/Mao.model3.json",
    "mark": f"{CDN}/Mark/Mark.model3.json",
    "rice": f"{CDN}/Rice/Rice.model3.json",
}


def get(url: str) -> bytes:
    last: Exception | None = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as exc:  # red flaky en CDN
            last = exc
            time.sleep(1.5)
    raise SystemExit(f"no pude bajar {url}: {last}")


def fetch(model3_url: str, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = get(model3_url)
    data = json.loads(raw)
    fr = data.get("FileReferences", {})
    refs: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, str) and value.strip() and "{" not in value:
            refs.add(value.strip())

    for key in ("Moc", "Physics", "DisplayInfo", "Pose", "UserData"):
        add(fr.get(key))
    for tex in fr.get("Textures") or []:
        add(tex)
    for motions in (fr.get("Motions") or {}).values():
        for entry in motions:
            add(entry.get("File"))
            add(entry.get("Sound"))
    for expr in fr.get("Expressions") or []:
        add(expr.get("File"))

    base = model3_url.rsplit("/", 1)[0]
    n = 0
    for rel in sorted(refs):
        dst = out_dir / rel
        if dst.is_file() and dst.stat().st_size:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(get(f"{base}/{urllib.parse.quote(rel)}"))
        n += 1
    (out_dir / Path(model3_url).name).write_bytes(raw)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rehacer aunque exista")
    args = ap.parse_args()
    for name, url in MODELS.items():
        if (DEST / name).is_dir() and not args.force:
            print(f"{name}: ya está")
            continue
        print(f"{name}: {fetch(url, DEST / name)} archivos")
    print("falta teto (VTube Studio): copiá el modelo a assets/live2d/teto/ si lo querés usar")
    print(f"modelos en {DEST}")
