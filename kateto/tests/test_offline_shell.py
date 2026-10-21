"""Tests del offline-first (SW + manifest + fallback local).

Estilo BDD del repo (# Given / # When / # Then). Cada test de ruta levanta su
propio HttpServer en un puerto libre de verdad (el test vecino usa 8998/8999).
"""

from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest

from kateto.core.manager import PluginManager
from kateto.plugins.system.http_server import WEB_DIR, HttpServer
from kateto.plugins.system.offline_shell import (
    CACHE_PREFIX,
    cache_name,
    collect_offline_assets,
    phone_urls,
)


def _free_port() -> int:
    # Given: un puerto libre de verdad (no fijo, para no chocar con 8998/8999).
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _running_server(config_dir: Path | None = None) -> tuple[HttpServer, str]:
    manager = PluginManager()
    port = _free_port()
    server = HttpServer(manager, host="127.0.0.1", port=port, config_dir=config_dir)
    await server.start()
    return server, f"http://127.0.0.1:{port}"


def test_collect_offline_assets_incluye_shell_y_componentes() -> None:
    # Given: el directorio web real del overlay.
    # When: se calcula la lista de assets.
    assets = collect_offline_assets(WEB_DIR)

    # Then: el shell va primero, los componentes clave están y no hay duplicados.
    assert assets[0] == "/overlay"
    assert "/components/kateto-avatar.js" in assets
    assert "/components/kateto-transcript.js" in assets
    assert "/components/kateto-offline.js" in assets
    assert len(assets) == len(set(assets))


def test_collect_offline_assets_excluye_modulos_de_test() -> None:
    # Given: el directorio web, que contiene kateto-avatar.test.mjs.
    # When: se calcula la lista de assets.
    assets = collect_offline_assets(WEB_DIR)

    # Then: ningún asset es un módulo de test.
    assert all(".test." not in asset for asset in assets)


def test_collect_offline_assets_incluye_avatares_de_voces_existentes(tmp_path: Path) -> None:
    # Given: una voz con avatar y una voz sin archivos.
    voices_dir = tmp_path / "voices"
    jane = voices_dir / "jane"
    jane.mkdir(parents=True)
    (jane / "avatar_head.png").write_bytes(b"head-bytes")
    (jane / "avatar_jaw.png").write_bytes(b"jaw-bytes")
    (voices_dir / "tmp").mkdir()

    # When: se calcula la lista de assets con voices_dir.
    assets = collect_offline_assets(WEB_DIR, voices_dir)

    # Then: los dos avatares de jane entran y la voz vacía no.
    assert "/voices/jane/avatar_head.png" in assets
    assert "/voices/jane/avatar_jaw.png" in assets
    assert not any(asset.startswith("/voices/tmp/") for asset in assets)


@pytest.mark.asyncio
async def test_service_worker_route_sirve_javascript_con_scope_raiz() -> None:
    # Given: un HttpServer levantado en un puerto libre.
    server, base = await _running_server()
    try:
        # When: pedimos el service worker.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/offline/sw.js")

        # Then: 200, JS con scope de raíz y el precache/activate esperados.
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]
        assert resp.headers["service-worker-allowed"] == "/"
        body = resp.text
        assert "addEventListener('install'" in body
        assert "clients.claim()" in body
        assert "const PRECACHE" in body
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_service_worker_usa_nombre_de_cache_con_hash() -> None:
    # Given: un HttpServer levantado en un puerto libre.
    server, base = await _running_server()
    try:
        # When: pedimos el service worker.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/offline/sw.js")

        # Then: el nombre de cache lleva el prefijo + versión con hash.
        assert resp.status_code == 200
        assert CACHE_PREFIX + "v1-" in resp.text
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_manifest_route_sirve_webmanifest_valido() -> None:
    # Given: un HttpServer levantado en un puerto libre.
    server, base = await _running_server()
    try:
        # When: pedimos el manifest.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/manifest.webmanifest")

        # Then: 200, media type de webmanifest y campos instalables.
        assert resp.status_code == 200
        assert "manifest+json" in resp.headers["content-type"]
        data = resp.json()
        assert data["start_url"] == "/overlay"
        assert data["display"] == "standalone"
        assert data["icons"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_todos_los_assets_precacheables_se_sirven(tmp_path: Path) -> None:
    # Given: un config_dir con un avatar existente.
    voices_dir = tmp_path / "voices" / "jane"
    voices_dir.mkdir(parents=True)
    (voices_dir / "avatar_head.png").write_bytes(b"head-bytes")

    assets = collect_offline_assets(WEB_DIR, tmp_path / "voices")
    server, base = await _running_server(config_dir=tmp_path)
    try:
        # When: pedimos cada asset que el SW va a precachear.
        async with httpx.AsyncClient() as client:
            for asset in assets:
                resp = await client.get(f"{base}{asset}")

                # Then: ninguno puede dar 404 (rompería el install del SW).
                assert resp.status_code == 200, f"{asset} -> {resp.status_code}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_icon_route_sirve_svg() -> None:
    # Given: un HttpServer levantado en un puerto libre.
    server, base = await _running_server()
    try:
        # When: pedimos el icono del manifest.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base}/offline/icon.svg")

        # Then: 200, SVG y el cuerpo arranca con <svg.
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/svg+xml")
        assert resp.text.startswith("<svg")
    finally:
        await server.stop()


def test_cache_name_cambia_con_el_conjunto_de_assets() -> None:
    # Given: dos conjuntos de assets distintos.
    # When: se calcula el nombre de cache de cada uno.
    one = cache_name(["/overlay"])
    two = cache_name(["/overlay", "/components/x.js"])

    # Then: el hash cambia y el prefijo se mantiene.
    assert one != two
    assert one.startswith("kateto-offline-v1-")
    assert two.startswith("kateto-offline-v1-")


def test_phone_urls_prioriza_mdns_y_filtra_no_privadas() -> None:
    # Given: un hostname mDNS y una mezcla de IPs privadas y públicas.
    # When: se calculan las URLs del teléfono.
    urls = phone_urls(8080, "kateto", ["192.168.1.7", "8.8.8.8", "10.0.0.3"])

    # Then: mDNS primero, después solo IPv4 privadas ordenadas.
    assert urls == [
        "http://kateto.local:8080/overlay",
        "http://10.0.0.3:8080/overlay",
        "http://192.168.1.7:8080/overlay",
    ]
