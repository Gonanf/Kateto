import asyncio
import httpx
import pytest

from kateto.core.manager import PluginManager
from kateto.plugins.system.http_server import HttpServer


@pytest.mark.asyncio
async def test_http_server_lifecycle_and_endpoints():
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=8999)

    await server.start()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8999/events")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)

            resp_plugins = await client.get("http://127.0.0.1:8999/plugins")
            assert resp_plugins.status_code == 200
            assert isinstance(resp_plugins.json(), list)
    finally:
        await server.stop()
