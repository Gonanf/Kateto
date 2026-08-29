from __future__ import annotations

import asyncio
import json
from loguru import logger
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kateto.core.event import EventEnvelope
from kateto.core.manager import PluginManager

log = logger

OVERLAY_HTML = Path(__file__).resolve().parent.parent / "visual_overlay" / "web" / "index.html"
COURTROOM_HTML = Path(__file__).resolve().parent.parent / "visual_overlay" / "web" / "courtroom.html"
VALID_AVATAR_FILES = ("top.png", "mouth.png", "avatar_head.png", "avatar_jaw.png")


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
    def __init__(
        self,
        manager: PluginManager,
        *,
        host: str = "127.0.0.1",
        port: int = 8080,
        config_dir: Path | None = None,
    ) -> None:
        self._manager = manager
        self._host = host
        self._port = port
        self._config_dir = config_dir
        self._app = self._build_app()
        self._server: Any = None
        self._observers: list[WebSocket] = []
        log.info("Initialized HttpServer instance for {}:{}", self._host, self._port)

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
                    receivers=list(reg.receivers),
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
                for p in self._manager.get_all_plugins()
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
            plugin = self._manager.get_plugin(name)
            if plugin is None:
                return {"error": f"plugin not found: {name}"}
            await self._manager.enable_plugin(plugin)
            return {"status": "ok"}

        @app.post("/plugins/{name}/disable")
        async def disable_plugin(name: str) -> dict[str, str]:
            plugin = self._manager.get_plugin(name)
            if plugin is None:
                return {"error": f"plugin not found: {name}"}
            await self._manager.disable_plugin(plugin.name)
            return {"status": "ok"}

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

        @app.get("/overlay")
        async def overlay() -> FileResponse:
            return FileResponse(OVERLAY_HTML)

        @app.get("/courtroom")
        async def courtroom() -> FileResponse:
            return FileResponse(COURTROOM_HTML)

        @app.get("/voices/{name}/{file}")
        async def voice_asset(name: str, file: str) -> FileResponse:
            if file not in VALID_AVATAR_FILES or self._config_dir is None:
                raise HTTPException(status_code=404, detail="not found")
            voices_dir = (self._config_dir / "voices").resolve()
            path = (voices_dir / name / file).resolve()
            try:
                if not path.is_relative_to(voices_dir) or not path.is_file():
                    raise HTTPException(status_code=404, detail="not found")
            except ValueError:
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(path)

        @app.websocket("/ws/overlay")
        async def overlay_stream(ws: WebSocket) -> None:
            await ws.accept()
            plugin = self._manager.get_plugin("visual_overlay")
            register = getattr(plugin, "register_websocket", None)
            unregister = getattr(plugin, "unregister_websocket", None)
            if register is None or unregister is None:
                await ws.close()
                return
            await register(ws)
            try:
                while True:
                    await ws.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                await unregister(ws)

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
        log.info("HttpServer.start called for {}:{}", self._host, self._port)
        config = uvicorn.Config(self._app, host=self._host, port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve(), name="kateto-http-server")
        for i in range(100):
            if self._server.started:
                log.info("uvicorn.Server.started is True after {} checks", i)
                break
            if self._serve_task.done():
                log.error("uvicorn serve_task finished early. Exception: {}", self._serve_task.exception())
                break
            await asyncio.sleep(0.05)
        if self._serve_task.done() and self._serve_task.exception() is not None:
            exc = self._serve_task.exception()
            log.error("HttpServer failed to start on {}:{}: {}", self._host, self._port, exc)
            raise exc  # type: ignore
        log.info("HTTP server started on {}:{}", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
