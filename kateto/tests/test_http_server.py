import asyncio
import httpx
import pytest

from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
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


@pytest.mark.asyncio
async def test_http_plugins_enable_and_disable_by_name():
    # Given: a registered-but-disabled plugin and an enabled plugin.
    manager = PluginManager()
    manager.register_plugin(Plugin("plugin_a"))
    plugin_b = Plugin("plugin_b")
    await manager.enable_plugin(plugin_b)
    server = HttpServer(manager, host="127.0.0.1", port=8998)

    await server.start()

    try:
        async with httpx.AsyncClient() as client:
            # Then: both plugins are listed, disabled plugin included.
            resp = await client.get("http://127.0.0.1:8998/plugins")
            status = {item["name"]: item["enabled"] for item in resp.json()}
            assert status == {"plugin_a": False, "plugin_b": True}

            # When: the disabled plugin is enabled and the enabled one disabled.
            resp = await client.post("http://127.0.0.1:8998/plugins/plugin_a/enable")
            assert resp.json() == {"status": "ok"}
            resp = await client.post("http://127.0.0.1:8998/plugins/plugin_b/disable")
            assert resp.json() == {"status": "ok"}

            # Then: state flipped.
            resp = await client.get("http://127.0.0.1:8998/plugins")
            status = {item["name"]: item["enabled"] for item in resp.json()}
            assert status == {"plugin_a": True, "plugin_b": False}
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_http_plugins_unknown_plugin_returns_error():
    # Given: an empty manager.
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=8997)

    await server.start()

    try:
        # When: an unknown plugin is enabled.
        async with httpx.AsyncClient() as client:
            resp = await client.post("http://127.0.0.1:8997/plugins/ghost/enable")

            # Then: an error is returned.
            assert resp.json() == {"error": "plugin not found: ghost"}
    finally:
        await server.stop()
