import re
import socket
import httpx
import pytest

from kateto.core.manager import PluginManager
from kateto.plugins.system.http_server import HttpServer, MASK_HTML


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_mask_endpoint_returns_html_and_expected_tags():
    # Given: a running HttpServer on an ephemeral port.
    port = _get_free_port()
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=port)
    await server.start()

    try:
        # When: requesting the /mask endpoint.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{port}/mask")

            # Then: response is 200, content-type contains text/html, body contains kateto-avatar and /ws/mask.
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            body = resp.text
            assert "kateto-avatar" in body
            assert "/ws/mask" in body
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mask_component_asset_resolves():
    # Given: a running HttpServer on an ephemeral port.
    port = _get_free_port()
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=port)
    await server.start()

    try:
        # When: requesting the kateto-avatar.js component imported by mask.html.
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{port}/components/kateto-avatar.js")

            # Then: response is 200 and contains component javascript code.
            assert resp.status_code == 200
            assert len(resp.text) > 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mask_html_static_analysis():
    # Given: the mask.html template file.
    assert MASK_HTML.is_file()
    content = MASK_HTML.read_text(encoding="utf-8")

    # Then: file size is greater than 8 KB.
    assert len(content.encode("utf-8")) > 8192

    # Then: no external http(s):// URLs outside localhost/127.0.0.1.
    urls = re.findall(r"https?://[^\s'\"`]+", content)
    for url in urls:
        assert "localhost" in url or "127.0.0.1" in url, f"External URL found: {url}"

    # Then: outbound payloads use type: and not event: for mask input.
    assert re.search(r"type:\s*['\"]mask_audio_input['\"]", content)
    assert re.search(r"type:\s*['\"]mask_camera_frame['\"]", content)
    assert not re.search(r"event:\s*['\"]mask_", content)

    # Then: internal payload keys match exactly.
    assert "audio:" in content
    assert "frame:" in content
    assert "dept:" in content
    assert "sample_rate: 16000" in content

    # Then: all four voices are present.
    for voice in ("doktor", "jane", "whisperer", "conquest"):
        assert voice in content
