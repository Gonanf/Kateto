"""Offline-first helpers for the Kateto phone overlay.

Módulo puro (sin FastAPI, sin manager): arma la lista de assets a precachear,
renderiza el Service Worker y el manifest, y calcula las URLs de LAN.

Reglas del brief:
- cero URLs externas (nada de CDNs, fuentes remotas ni analytics),
- primer asset siempre ``/overlay`` (el shell),
- los módulos ``*.test.*`` nunca se precachean.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from pathlib import Path
from typing import Any

SHELL_URL = "/overlay"
SW_URL = "/offline/sw.js"
MANIFEST_URL = "/manifest.webmanifest"
ICON_URL = "/offline/icon.svg"
CACHE_PREFIX = "kateto-offline-"
SPEECH_LANG = "es-AR"

# SVG mínimo propio (~200 bytes). El atributo xmlns es el namespace XML del
# formato, no un recurso descargable: no hay ninguna URL externa.
ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#0b0b0f"/>'
    '<circle cx="32" cy="24" r="12" fill="#fde68a"/>'
    '<path d="M12 56c3-12 11-18 20-18s17 6 20 18z" fill="#78350f"/>'
    "</svg>"
)

_AVATAR_FILES = ("avatar_head.png", "avatar_jaw.png")


def collect_offline_assets(web_dir: Path, voices_dir: Path | None = None) -> list[str]:
    """Lista de URLs same-origin que el Service Worker debe precachear.

    El primer elemento es siempre el shell (``/overlay``); después van los
    ``*.js`` de ``web_dir`` en orden alfabético (los módulos de test quedan
    afuera) y, si se pasa ``voices_dir``, los avatares que existan por voz.
    Sin duplicados, sin URLs externas, sin query strings.
    """
    assets: list[str] = [SHELL_URL]
    seen: set[str] = {SHELL_URL}

    def add(asset: str) -> None:
        if asset not in seen:
            seen.add(asset)
            assets.append(asset)

    if web_dir.is_dir():
        for path in sorted(web_dir.glob("*.js"), key=lambda p: p.name):
            if ".test." in path.name:
                continue
            add(f"/components/{path.name}")

    if voices_dir is not None and voices_dir.is_dir():
        voice_dirs = sorted(
            (p for p in voices_dir.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
        for voice_dir in voice_dirs:
            for name in _AVATAR_FILES:
                if (voice_dir / name).is_file():
                    add(f"/voices/{voice_dir.name}/{name}")

    return assets


def cache_name(assets: list[str]) -> str:
    """Nombre de cache versionado por hash del conjunto de assets."""
    digest = hashlib.sha256("\n".join(assets).encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}v1-{digest[:12]}"


def render_service_worker(assets: list[str]) -> str:
    """Cuerpo JS del Service Worker (sin importScripts, sin workbox, sin red externa)."""
    cache = cache_name(assets)
    precache = json.dumps(assets)
    return (
        "// Kateto offline shell — generado por offline_shell.py\n"
        f'const CACHE = "{cache}";\n'
        f"const PRECACHE = {precache};\n"
        f'const CACHE_PREFIX = "{CACHE_PREFIX}";\n'
        f'const SHELL_URL = "{SHELL_URL}";\n'
        "\n"
        "self.addEventListener('install', (e) => {\n"
        "  e.waitUntil(\n"
        "    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())\n"
        "  );\n"
        "});\n"
        "\n"
        "self.addEventListener('activate', (e) => {\n"
        "  e.waitUntil(\n"
        "    caches.keys()\n"
        "      .then((keys) => Promise.all(\n"
        "        keys.filter((k) => k.startsWith(CACHE_PREFIX) && k !== CACHE).map((k) => caches.delete(k))\n"
        "      ))\n"
        "      .then(() => self.clients.claim())\n"
        "  );\n"
        "});\n"
        "\n"
        "self.addEventListener('fetch', (e) => {\n"
        "  if (e.request.method !== 'GET') return;\n"
        "  const url = new URL(e.request.url);\n"
        "  if (url.origin !== self.location.origin) return;\n"
        "  if (url.pathname.startsWith('/ws/') || url.pathname.startsWith('/api/')) return;\n"
        "  if (e.request.mode === 'navigate') {\n"
        "    e.respondWith(\n"
        "      fetch(e.request).catch(() =>\n"
        "        caches.match(SHELL_URL).then((hit) => hit || caches.match(e.request))\n"
        "      )\n"
        "    );\n"
        "    return;\n"
        "  }\n"
        "  // cache-first; ignoreSearch cubre los imports versionados con ?v=\n"
        "  e.respondWith(\n"
        "    caches.match(e.request).then(\n"
        "      (hit) => hit || caches.match(e.request, { ignoreSearch: true })\n"
        "        .then((alt) => alt || fetch(e.request))\n"
        "    )\n"
        "  );\n"
        "});\n"
    )


def build_manifest() -> dict:
    """Web app manifest JSON-serializable para instalar el overlay en el teléfono."""
    return {
        "name": "Kateto",
        "short_name": "Kateto",
        "start_url": SHELL_URL,
        "scope": "/",
        "display": "standalone",
        "background_color": "#0b0b0f",
        "theme_color": "#0b0b0f",
        "lang": SPEECH_LANG,
        "icons": [
            {
                "src": ICON_URL,
                "sizes": "any",
                "type": "image/svg+xml",
                "purpose": "any",
            }
        ],
    }


def phone_urls(port: int, hostname: str = "", addresses: list[str] | None = None) -> list[str]:
    """URLs del overlay para el teléfono: mDNS primero, después IPv4 privadas."""
    urls: list[str] = []
    if hostname:
        urls.append(f"http://{hostname}.local:{port}{SHELL_URL}")
    for addr in sorted(set(addresses or [])):
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private:
            urls.append(f"http://{addr}:{port}{SHELL_URL}")
    return urls


def local_ipv4_addresses() -> list[str]:
    """Best-effort: IPv4 privadas de esta máquina (``[]`` si el host falla)."""
    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
    except Exception:
        return []
    result: list[str] = []
    for addr in ips:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private:
            result.append(addr)
    return result
