from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from kateto.core.config import register_plugin_param
from kateto.core.event import GenerateData, TextChunk
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin

log = logger


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "jane"
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


class CompletionRequest(BaseModel):
    model: str = "jane"
    prompt: str | list[str] = ""
    stream: bool = False
    max_tokens: int | None = None


def extract_prompt_from_messages(messages: list[ChatMessage]) -> str:
    """Flatten OpenAI messages into an expressive prompt preserving context."""
    if not messages:
        return ""
    if len(messages) == 1 and messages[0].role == "user":
        return messages[0].content.strip()

    parts = []
    for msg in messages:
        role = (msg.role or "user").lower()
        content = (msg.content or "").strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"[Instrucción del Sistema]: {content}")
        elif role == "assistant":
            parts.append(f"[Asistente]: {content}")
        else:
            name_tag = f" ({msg.name})" if msg.name else ""
            parts.append(f"[Usuario{name_tag}]: {content}")
    return "\n\n".join(parts)


def get_available_voices(manager: PluginManager) -> list[str]:
    """Retrieve all available Kateto voice IDs from the manager."""
    voices: set[str] = set()
    plugins = manager.get_plugins() if hasattr(manager, "get_plugins") else []
    for plugin in plugins:
        name = plugin.name.casefold()
        if hasattr(plugin, "role") or name in {"jane", "doktor", "conquest", "whisperer"}:
            voices.add(name)
    if not voices:
        voices = {"jane", "doktor", "conquest", "whisperer"}
    return sorted(voices)


def create_openai_router(manager: PluginManager, default_voice: str = "jane") -> APIRouter:
    """Build FastAPI router exposing OpenAI-compatible endpoints over Kateto event bus."""
    router = APIRouter(prefix="/v1", tags=["OpenAI"])

    @router.get("/models")
    async def list_models() -> dict[str, Any]:
        voices = get_available_voices(manager)
        created_time = int(time.time())
        return {
            "object": "list",
            "data": [
                {
                    "id": vid,
                    "object": "model",
                    "created": created_time,
                    "owned_by": "kateto",
                    "permission": [],
                    "root": vid,
                    "parent": None,
                }
                for vid in voices
            ],
        }

    @router.get("/models/{model_id:path}")
    async def get_model(model_id: str) -> dict[str, Any]:
        voices = get_available_voices(manager)
        vid = model_id.casefold()
        if vid not in voices:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "message": f"Model '{model_id}' not found. Available models: {', '.join(voices)}",
                        "type": "invalid_request_error",
                        "param": "model",
                        "code": "model_not_found",
                    }
                },
            )
        return {
            "id": vid,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "kateto",
        }

    async def _execute_turn(
        target_vid: str,
        prompt: str,
        timeout: float = 120.0,
    ) -> tuple[asyncio.Queue[tuple[str, bool]], asyncio.Task[None]]:
        """Dispatch turn to Kateto event bus and prepare async token queue."""
        queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        done_event = asyncio.Event()

        def _observer(envelope) -> None:
            if envelope.name == "text_chunk":
                chunk_vid = str(getattr(envelope.data, "voice_id", "") or envelope.source).casefold()
                if chunk_vid == target_vid:
                    txt = getattr(envelope.data, "text", "")
                    final = bool(getattr(envelope.data, "final", False))
                    queue.put_nowait((txt, final))
                    if final:
                        done_event.set()
            elif envelope.name == "voice_idle":
                idle_vid = str(getattr(envelope.data, "voice", "") or envelope.source).casefold()
                if idle_vid == target_vid:
                    queue.put_nowait(("", True))
                    done_event.set()

        manager.add_event_observer(_observer)

        async def _run() -> None:
            try:
                target_plugin = manager.get_plugin(target_vid) or manager.get_plugin(target_vid.capitalize())
                if target_plugin is not None and hasattr(target_plugin, "on_generate"):
                    await target_plugin.on_generate(GenerateData(prompt=prompt))
                else:
                    await manager.emit("generate", GenerateData(prompt=prompt), target=target_vid, source="openai_api")
                await asyncio.wait_for(done_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                log.warning("Generation timed out for voice '{}' after {}s", target_vid, timeout)
                queue.put_nowait(("", True))
            except Exception as exc:
                log.exception("Error executing turn for voice '{}': {}", target_vid, exc)
                queue.put_nowait(("", True))
            finally:
                manager.remove_event_observer(_observer)

        run_task = asyncio.create_task(_run())
        return queue, run_task

    @router.post("/chat/completions")
    async def chat_completions(req: ChatCompletionRequest, raw_request: Request) -> Any:
        target_vid = req.model.casefold() if req.model else default_voice
        prompt = extract_prompt_from_messages(req.messages)

        if not prompt.strip():
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": "messages must contain at least one non-empty content", "type": "invalid_request_error"}},
            )

        req_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created_time = int(time.time())

        queue, run_task = await _execute_turn(target_vid, prompt)

        if req.stream:
            async def sse_generator() -> AsyncGenerator[str, None]:
                first_sent = False
                try:
                    # Initial chunk specifying role
                    init_chunk = {
                        "id": req_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": target_vid,
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(init_chunk)}\n\n"

                    while True:
                        if await raw_request.is_disconnected():
                            run_task.cancel()
                            break

                        txt, final = await queue.get()
                        if txt:
                            chunk_payload = {
                                "id": req_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": target_vid,
                                "choices": [{"index": 0, "delta": {"content": txt}, "finish_reason": None}],
                            }
                            yield f"data: {json.dumps(chunk_payload)}\n\n"
                            first_sent = True

                        if final:
                            final_payload = {
                                "id": req_id,
                                "object": "chat.completion.chunk",
                                "created": created_time,
                                "model": target_vid,
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            }
                            yield f"data: {json.dumps(final_payload)}\n\n"
                            break

                    yield "data: [DONE]\n\n"
                finally:
                    if not run_task.done():
                        run_task.cancel()

            return StreamingResponse(
                sse_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Non-streaming aggregation
        collected: list[str] = []
        try:
            while True:
                txt, final = await queue.get()
                if txt:
                    collected.append(txt)
                if final:
                    break
        finally:
            if not run_task.done():
                run_task.cancel()

        full_content = "".join(collected).strip()
        p_tokens = len(prompt.split())
        c_tokens = len(full_content.split())

        return {
            "id": req_id,
            "object": "chat.completion",
            "created": created_time,
            "model": target_vid,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": p_tokens,
                "completion_tokens": c_tokens,
                "total_tokens": p_tokens + c_tokens,
            },
        }

    @router.post("/completions")
    async def legacy_completions(req: CompletionRequest, raw_request: Request) -> Any:
        prompt = req.prompt if isinstance(req.prompt, str) else "\n".join(req.prompt)
        chat_req = ChatCompletionRequest(
            model=req.model,
            messages=[ChatMessage(role="user", content=prompt)],
            stream=req.stream,
        )
        return await chat_completions(chat_req, raw_request)

    return router


class OpenAIServerPlugin(Plugin):
    """Plugin providing an OpenAI-compatible API interface over Kateto's native event bus."""

    def __init__(
        self,
        name: str = "openai_server",
        manager: PluginManager | None = None,
        default_voice: str = "jane",
    ) -> None:
        super().__init__(name=name, capabilities=("system", "api", "openai"))
        self.default_voice = default_voice
        self._router: APIRouter | None = None

    def get_router(self, manager: PluginManager) -> APIRouter:
        if self._router is None:
            self._router = create_openai_router(manager, default_voice=self.default_voice)
        return self._router

    async def on_text_chunk(self, data: TextChunk) -> None:
        pass


register_plugin_param("openai_server", "enabled", True)
register_plugin_param("openai_server", "default_voice", "jane")
register_plugin_param("openai_server", "timeout", 120.0)
