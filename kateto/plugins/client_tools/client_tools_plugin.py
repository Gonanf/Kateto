"""Client tools: las herramientas que ejecuta el telefono, expuestas a las voces.

El telefono (app `com.kateto.phone`) al abrir el WS manda `client_register` con sus
capacidades. Cuando una voz llama a una tool `client_*`, este plugin emite
`client_tool_request` — que `HttpServer` reenvia a los observadores WS como frame —
y espera el `tool_result` que el telefono postea a /events/send.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from kateto.core.plugin import Plugin

REQUEST_TIMEOUT_S = 8.0


class ClientRegisterData(BaseModel):
    client_id: str = ""
    capabilities: list[str] = Field(default_factory=list)
    tool_version: int = 1
    app_version: str = ""
    model: str = ""


class ClientToolRequestData(BaseModel):
    request_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = int(REQUEST_TIMEOUT_S * 1000)


class ToolResultData(BaseModel):
    request_id: str
    status: str = "ok"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    client_ts: int = 0
    duration_ms: int = 0


# Esquema de las tools que el telefono sabe ejecutar (ClientTools.kt).
CLIENT_TOOL_DEFS: tuple[dict[str, Any], ...] = (
    {
        "name": "client_flashlight",
        "description": "Prende o apaga la linterna del telefono.",
        "parameters": {
            "type": "object",
            "properties": {"on": {"type": "boolean", "description": "true prende, false apaga"}},
            "required": ["on"],
        },
    },
    {
        "name": "client_location",
        "description": "Ultima ubicacion conocida del telefono (lat, lon, precision, proveedor).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "client_battery",
        "description": "Estado de bateria del telefono (porcentaje, cargando, fuente).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "client_network",
        "description": "Tipo de red y estado de conexion del telefono.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "client_bluetooth",
        "description": "Estado del adaptador bluetooth y dispositivos conectados del telefono.",
        "parameters": {"type": "object", "properties": {}},
    },
)


class ClientToolsPlugin(Plugin):
    def __init__(self, name: str = "client_tools") -> None:
        super().__init__(name=name, capabilities=("tools", "client_tools"))
        self.client_id: str | None = None
        self.capabilities: set[str] = set()
        self._pending: dict[str, asyncio.Future[ToolResultData]] = {}

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("client_register", ClientRegisterData)
            self.manager.register_event("client_tool_request", ClientToolRequestData)
            self.manager.register_event("tool_result", ToolResultData)

    async def on_client_register(self, data: ClientRegisterData, envelope: Any = None) -> None:
        self.client_id = data.client_id or "phone"
        self.capabilities = {c for c in data.capabilities if isinstance(c, str)}
        logger.info("[client_tools] telefono registrado: {} caps={}", self.client_id, sorted(self.capabilities))

    async def on_tool_result(self, data: ToolResultData, envelope: Any = None) -> None:
        future = self._pending.pop(data.request_id, None)
        if future is None:
            logger.debug("[client_tools] tool_result huerfano {}", data.request_id)
            return
        if not future.done():
            future.set_result(data)

    def tool_definitions(self) -> tuple[dict[str, Any], ...]:
        """Siempre las 5: las voces se arman en el enable(), antes de que el
        telefono se registre. Si el telefono no tiene el periferico, devuelve
        unknown_tool y la voz lo dice."""
        return tuple({"type": "function", "function": d} for d in CLIENT_TOOL_DEFS)

    async def call(self, tool: str, arguments: dict[str, Any], timeout_s: float = REQUEST_TIMEOUT_S) -> str:
        import json

        if self.manager is None:
            return json.dumps({"error": "sin plugin manager"})
        if self.client_id is None:
            return json.dumps({"error": "no hay telefono registrado"})
        request_id = uuid4().hex
        future: asyncio.Future[ToolResultData] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self.manager.emit(
                "client_tool_request",
                ClientToolRequestData(
                    request_id=request_id,
                    tool=tool,
                    arguments=arguments,
                    timeout_ms=int(timeout_s * 1000),
                ),
                source="client_tools",
            )
            result = await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.TimeoutError:
            return json.dumps({"error": f"el telefono no respondio {tool} en {timeout_s}s"})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": f"fallo {tool}: {exc}"})
        finally:
            self._pending.pop(request_id, None)
        if result.status != "ok":
            return json.dumps({"error": result.error or result.status})
        return json.dumps(result.result)
