#!/usr/bin/env python3
"""Sirve el repo para la escena de entrevista: rutas normales + `/media/` sobre `assets/`.

Uso: python3 scripts/serve_scene.py [--port 8791]
La escena queda en http://127.0.0.1:<port>/hipotenusa/plugins/visual_overlay/web/interview-event.html
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        if path.startswith("/media/"):
            rel = urllib.parse.unquote(path[len("/media/"):].split("?", 1)[0].split("#", 1)[0])
            return str(REPO / "assets" / rel)
        return super().translate_path(path)

    def log_message(self, format: str, *args) -> None:  # silencio: sólo importa el HTTP status
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()
    os.chdir(REPO)
    handler = functools.partial(Handler, directory=str(REPO))
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
