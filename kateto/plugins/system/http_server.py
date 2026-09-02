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

from kateto.core.event import EventEnvelope, InterruptData, TextChunk
from kateto.core.manager import PluginManager

log = logger

OVERLAY_HTML = Path(__file__).resolve().parent.parent / "visual_overlay" / "web" / "index.html"
COURTROOM_HTML = Path(__file__).resolve().parent.parent / "visual_overlay" / "web" / "courtroom.html"
WEB_DIR = Path(__file__).resolve().parent.parent / "visual_overlay" / "web"
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

        class NoCacheMiddleware:
            def __init__(self, app: Any) -> None:
                self.app = app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                async def send_wrapper(message: Any) -> None:
                    if message["type"] == "http.response.start":
                        headers = list(message.get("headers", []))
                        headers.append((b"cache-control", b"no-cache, no-store, must-revalidate, max-age=0"))
                        headers.append((b"pragma", b"no-cache"))
                        headers.append((b"expires", b"0"))
                        message = dict(message)
                        message["headers"] = headers
                    await send(message)

                await self.app(scope, receive, send_wrapper)

        app.add_middleware(NoCacheMiddleware)

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

        SOUNDS_DIR = (Path(__file__).resolve().parent.parent / "bate_debate" / "sounds").resolve()

        @app.get("/components/{file}")
        async def component_asset(file: str) -> FileResponse:
            path = (WEB_DIR / file).resolve()
            if not path.is_relative_to(WEB_DIR) or not path.is_file():
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(path)

        @app.get("/sounds/{file}")
        async def sound_asset(file: str) -> FileResponse:
            path = (SOUNDS_DIR / file).resolve()
            if not path.is_relative_to(SOUNDS_DIR) or not path.is_file():
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(path)

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

        @app.get("/api/courtroom/state")
        async def courtroom_state() -> dict[str, Any]:
            plugin = self._manager.get_plugin("visual_overlay")
            last_state = getattr(plugin, "_last_debate_state", None)
            history = getattr(plugin, "_debate_history", [])
            return {"current": last_state, "history": history}

        @app.post("/api/game/event")
        async def game_event(payload: dict[str, Any]) -> dict[str, Any]:
            log.info("game_event {} {} {}", payload.get("game"), payload.get("event_type"), payload.get("voice_id"))
            bridge = self._manager.get_plugin("game_bridge")
            result = {"status": "ok"}
            event_data = payload
            if bridge is not None and hasattr(bridge, "handle_event"):
                try:
                    result = await bridge.handle_event(payload)
                    event_data = result.get("event", payload)
                except Exception as exc:
                    log.warning("game_bridge handle_event failed: {}", exc)
            if (event_data.get("event_type") or event_data.get("type")) == "move_request":
                try:
                    from kateto.core.event import GenerateData
                    st = event_data.get("state") or {}
                    fen = st.get("fen","")
                    legal = st.get("legal_moves") or []
                    req = st.get("request_id","")
                    voice = str(event_data.get("voice_id") or "jane")
                    color = st.get("color","")
                    opponent = st.get("opponent","")
                    history = st.get("history","")
                    prompt = f"[CHESS GameMode] Sos {voice} con {color} vs {opponent}. FEN:{fen} Historial:{history} Legales:{legal[:12]} request_id={req}. Respondé SOLO con un UCI de Legales (ej e2e4), sin texto extra."
                    log.info("game move_request -> emit generate for {} req {}", voice, req)
                    await self._manager.emit("generate", GenerateData(prompt=prompt), source="game_bridge", target=voice)
                    log.info("generate emitted for {}", voice)
                except Exception as exc:
                    log.warning("game generate emit failed: {}", exc)
            # broadcast to visual_overlay for OBS overlay
            vo = self._manager.get_plugin("visual_overlay")
            if vo is not None and hasattr(vo, "_broadcast"):
                try:
                    text = str(event_data.get("text") or "")
                    voice_id = str(event_data.get("voice_id") or "jane")
                    game = str(event_data.get("game") or "unknown")
                    rms = float(event_data.get("rms", event_data.get("rms_hint", 0.12)) or 0.12)
                    # subtitle
                    await vo._broadcast({
                        "event": "text_chunk",
                        "type": "subtitle",
                        "text": text,
                        "voice_id": voice_id,
                        "game": game,
                        "data": {"text": text, "voice_id": voice_id, "game": game},
                    })
                    # viseme
                    from kateto.core.rms import map_rms_to_jaw_transform
                    oy, rot = map_rms_to_jaw_transform(rms)
                    await vo._broadcast({
                        "event": "audio_output",
                        "type": "viseme",
                        "voice_id": voice_id,
                        "rms": rms,
                        "is_speaking": bool(rms > 0.01 and text),
                        "jawOffsetY": oy,
                        "jawRotation": rot,
                        "game": game,
                        "data": {"rms": rms, "voice_id": voice_id, "game": game},
                    })
                    await vo._broadcast(event_data if isinstance(event_data, dict) else payload)
                except Exception as exc:
                    log.warning("visual_overlay broadcast failed: {}", exc)
            return result

        @app.get("/api/game/state")
        async def game_state(game: str | None = None) -> dict[str, Any]:
            bridge = self._manager.get_plugin("game_bridge")
            if bridge is not None and hasattr(bridge, "get_state"):
                try:
                    return bridge.get_state(game)
                except Exception:
                    pass
            # fallback to visual_overlay last state
            vo = self._manager.get_plugin("visual_overlay")
            if vo is not None:
                return {"game": game, "current": getattr(vo, "_last_debate_state", None)}
            return {"game": game, "current": None}

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
            # Relay any message received on this socket (e.g. a debate turn pushed
            # by `kateto debate --overlay`) to every other connected overlay client
            # (e.g. courtroom.html), so the courtroom renders the debate live.
            connected = getattr(plugin, "_connected_websockets", None)
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and parsed.get("event") == "debate":
                            plugin._last_debate_state = parsed
                            hist = getattr(plugin, "_debate_history", None)
                            if isinstance(hist, list):
                                hist.append(parsed)
                                if len(hist) > 50:
                                    hist.pop(0)


                    except Exception:
                        pass

                    if connected is None:
                        continue
                    for other in list(connected):
                        if other is ws:
                            continue
                        try:
                            await other.send_text(data)
                        except Exception:  # noqa: BLE001
                            try:
                                connected.discard(other)
                            except Exception:  # noqa: BLE001
                                pass
            except WebSocketDisconnect:
                pass
            finally:
                await unregister(ws)
        try:
            from kateto.plugins.system.openai_server import create_openai_router
            app.include_router(create_openai_router(self._manager))
        except Exception as exc:
            log.warning("Failed to mount OpenAI router: {}", exc)

        return app

    def _on_event(self, envelope: EventEnvelope[Any]) -> None:
        try:
            if envelope.name == "tool_call":
                d = envelope.data.model_dump() if hasattr(envelope.data, "model_dump") else {}
                args = d.get("arguments") or {}
                uci = args.get("uci") or args.get("move") or d.get("uci")
                req = args.get("request_id") or d.get("request_id")
                if uci and isinstance(uci, str) and len(uci) >= 4:
                    log.info("tool_call -> game_action {} req {}", uci, req)
                    bridge = self._manager.get_plugin("game_bridge")
                    if bridge is not None and hasattr(bridge, "handle_event"):
                        import asyncio as _aio
                        payload_gc = {"game":"chess","event_type":"game_action","voice_id":d.get("voice") or envelope.target or "jane","text":uci,"rms":0.2,"state":{"uci":uci.lower().strip(),"request_id":req}}
                        _aio.get_event_loop().create_task(bridge.handle_event(payload_gc))
            elif envelope.name == "text_chunk":
                d = envelope.data.model_dump() if hasattr(envelope.data, "model_dump") else {}
                txt = (d.get("text") or "")
                if txt:
                    import re as _re
                    for tok in _re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?", txt.lower()):
                        cand = tok.strip(".,;:")
                        if len(cand) >= 4 and cand[0] in "abcdefgh" and cand[1] in "12345678":
                            log.info("text_chunk -> game_action {} from {}", cand, d.get("voice_id") or envelope.target)
                            bridge = self._manager.get_plugin("game_bridge")
                            if bridge is not None and hasattr(bridge, "handle_event"):
                                import asyncio as _aio
                                payload_gc = {"game":"chess","event_type":"game_action","voice_id":d.get("voice_id") or envelope.target or "jane","text":cand,"rms":0.2,"state":{"uci":cand}}
                                _aio.get_event_loop().create_task(bridge.handle_event(payload_gc))
                            break
        except Exception:
            pass
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
