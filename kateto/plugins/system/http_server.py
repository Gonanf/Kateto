from __future__ import annotations

import asyncio
import json
from loguru import logger
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from kateto.core.event import EventEnvelope
from kateto.core.manager import PluginManager

log = logger


class EventListItem(BaseModel):
    name: str
    contract: dict[str, Any] | None = None
    receivers: list[str] = []


class VoiceStatus(BaseModel):
    name: str
    enabled: bool
    speaking: bool = False


class PluginStatus(BaseModel):
    name: str
    enabled: bool
    capabilities: list[str] = []


class SendEventRequest(BaseModel):
    event_name: str
    data: dict[str, Any] = {}
    target: str | None = None


class HttpServer:
    def __init__(self, manager: PluginManager, *, host: str = "127.0.0.1", port: int = 8080) -> None:
        self._manager = manager
        self._host = host
        self._port = port
        self._app = self._build_app()
        self._server: Any = None
        self._observers: list[WebSocket] = []

    def _build_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            self._manager.add_event_observer(self._on_event)
            yield
            self._manager.remove_event_observer(self._on_event)

        app = FastAPI(title="Kateto HTTP Server", lifespan=lifespan)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.get("/events")
        async def list_events() -> list[EventListItem]:
            items: list[EventListItem] = []
            for reg in self._manager.get_event_registrations():
                contract_schema = None
                if reg.contract is not None:
                    contract_schema = reg.contract.model_json_schema()
                items.append(EventListItem(
                    name=reg.name,
                    contract=contract_schema,
                    receivers=[r.name for r in reg.receivers],
                ))
            return items

        @app.get("/voices")
        async def list_voices() -> list[VoiceStatus]:
            voices: list[VoiceStatus] = []
            for plugin in self._manager.get_plugins():
                if "voice" not in plugin.capabilities:
                    continue
                voices.append(VoiceStatus(
                    name=plugin.name,
                    enabled=plugin.enabled,
                ))
            return voices

        @app.get("/plugins")
        async def list_plugins() -> list[PluginStatus]:
            return [
                PluginStatus(
                    name=p.name,
                    enabled=p.enabled,
                    capabilities=list(p.capabilities),
                )
                for p in self._manager.get_plugins()
            ]

        @app.post("/events/send")
        async def send_event(request: SendEventRequest) -> dict[str, str]:
            from pydantic import TypeAdapter
            contract = self._manager.get_event_registrations()
            registration = next((r for r in contract if r.name == request.event_name), None)
            if registration is None:
                return {"error": f"unknown event: {request.event_name}"}
            if registration.contract is not None:
                try:
                    data = registration.contract.model_validate(request.data)
                except Exception as exc:
                    return {"error": f"invalid data: {exc}"}
            else:
                from pydantic import BaseModel as _BM
                data = _BM.model_validate(request.data)
            await self._manager.emit(
                request.event_name,
                data,
                source="http_server",
                target=request.target,
            )
            return {"status": "ok"}

        @app.post("/plugins/{name}/enable")
        async def enable_plugin(name: str) -> dict[str, str]:
            for plugin in self._manager.get_plugins():
                if plugin.name == name:
                    await self._manager.enable_plugin(plugin)
                    return {"status": "ok"}
            return {"error": f"plugin not found: {name}"}

        @app.post("/plugins/{name}/disable")
        async def disable_plugin(name: str) -> dict[str, str]:
            for plugin in self._manager.get_plugins():
                if plugin.name == name:
                    await self._manager.disable_plugin(plugin)
                    return {"status": "ok"}
            return {"error": f"plugin not found: {name}"}

        @app.websocket("/events/stream")
        async def event_stream(ws: WebSocket) -> None:
            await ws.accept()
            self._observers.append(ws)
            try:
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                self._observers.remove(ws)

        return app

    def _on_event(self, envelope: EventEnvelope[Any]) -> None:
        payload = {
            "name": envelope.name,
            "source": envelope.source,
            "target": envelope.target,
            "timestamp": envelope.timestamp.isoformat(),
            "trace_id": envelope.trace_id,
            "data": envelope.data.model_dump(),
        }
        dead: list[WebSocket] = []
        for ws in self._observers:
            try:
                asyncio.get_event_loop().create_task(ws.send_json(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._observers.remove(ws)

    async def start(self) -> None:
        import uvicorn
        config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve(), name="kateto-http-server")
        log.info("HTTP server started on {}:{}", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
