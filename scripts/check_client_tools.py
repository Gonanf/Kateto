"""Check del puente de client tools (sin runtime ni telefono).

Corre: .venv/bin/python scripts/check_client_tools.py
Falla si: no se anuncian las 5 tools, o si call() no resuelve con el tool_result.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

sys.path.insert(0, ".")

from kateto.plugins.client_tools.client_tools_plugin import (  # noqa: E402
    CLIENT_TOOL_DEFS,
    ClientRegisterData,
    ClientToolsPlugin,
    ToolResultData,
)


class StubManager:
    """Captura lo emitido y simula al telefono respondiendo el tool_call."""

    def __init__(self, plugin_ref: list[ClientToolsPlugin]) -> None:
        self.emitted: list[tuple[str, Any]] = []
        self._plugin_ref = plugin_ref
        self.events: dict[str, Any] = {}

    def register_event(self, name: str, contract: Any) -> None:
        self.events[name] = contract

    async def emit(self, name: str, data: Any, **_: Any) -> None:
        self.emitted.append((name, data))
        plugin = self._plugin_ref[0]
        if name == "client_tool_request":
            # el telefono contesta en el mismo tick
            asyncio.get_running_loop().create_task(
                plugin.on_tool_result(
                    ToolResultData(request_id=data.request_id, status="ok", result={"pct": 42})
                )
            )


async def main() -> None:
    plugin = ClientToolsPlugin()
    manager = StubManager([plugin])
    plugin.manager = manager  # type: ignore[assignment]

    names = [definition["name"] for definition in CLIENT_TOOL_DEFS]
    assert names == [
        "client_flashlight",
        "client_location",
        "client_battery",
        "client_network",
        "client_bluetooth",
    ], names
    assert len(plugin.tool_definitions()) == len(CLIENT_TOOL_DEFS)
    assert all(t["type"] == "function" for t in plugin.tool_definitions())

    # sin telefono registrado no se puede llamar
    out = json.loads(await plugin.call("client_battery", {}))
    assert "no hay telefono" in out["error"], out

    await plugin.on_client_register(
        ClientRegisterData(client_id="test", capabilities=["battery"])
    )
    assert plugin.client_id == "test"

    out = json.loads(await plugin.call("client_battery", {}))
    assert out == {"pct": 42}, out
    assert manager.emitted[-1][0] == "client_tool_request"
    assert manager.emitted[-1][1].tool == "client_battery"

    # un error del telefono se propaga como error, no como {}
    fut = asyncio.create_task(plugin.call("client_location", {}))
    await asyncio.sleep(0)
    request = manager.emitted[-1][1]
    await plugin.on_tool_result(
        ToolResultData(request_id=request.request_id, status="error", error="no_fix")
    )
    assert json.loads(await fut) == {"error": "no_fix"}

    print("check_client_tools: ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
