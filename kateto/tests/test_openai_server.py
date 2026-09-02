import asyncio
import json
import pytest
from httpx import ASGITransport, AsyncClient

from kateto.core.event import GenerateData, TextChunk
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.system.openai_server import OpenAIServerPlugin, create_openai_router


class MockVoicePlugin(Plugin):
    """Mock VoiceAgent responding to on_generate with streamed TextChunks."""

    def __init__(self, name: str = "jane") -> None:
        super().__init__(name=name)
        self.received_prompts: list[str] = []

    async def on_generate(self, data: GenerateData) -> None:
        self.received_prompts.append(data.prompt or "")
        if self.manager is not None:
            await self.manager.emit(
                "text_chunk",
                TextChunk(text="Hola ", sequence=0, final=False, voice_id=self.name),
                source=self.name,
            )
            await asyncio.sleep(0.01)
            await self.manager.emit(
                "text_chunk",
                TextChunk(text="desde ", sequence=1, final=False, voice_id=self.name),
                source=self.name,
            )
            await asyncio.sleep(0.01)
            await self.manager.emit(
                "text_chunk",
                TextChunk(text="Kateto.", sequence=2, final=True, voice_id=self.name),
                source=self.name,
            )
            await self.manager.emit(
                "voice_idle",
                data=self,
                source=self.name,
            )


@pytest.mark.asyncio
async def test_openai_list_and_get_models():
    manager = PluginManager()
    voice_jane = MockVoicePlugin("jane")
    voice_doktor = MockVoicePlugin("doktor")
    manager.register_plugin(voice_jane)
    manager.register_plugin(voice_doktor)

    server = HttpServer(manager, host="127.0.0.1", port=8991)
    app = server._app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /v1/models
        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        model_ids = [m["id"] for m in data["data"]]
        assert "jane" in model_ids
        assert "doktor" in model_ids

        # GET /v1/models/jane
        resp_model = await client.get("/v1/models/jane")
        assert resp_model.status_code == 200
        assert resp_model.json()["id"] == "jane"

        # GET /v1/models/nonexistent
        resp_404 = await client.get("/v1/models/nonexistent")
        assert resp_404.status_code == 404

    await manager.close()


@pytest.mark.asyncio
async def test_openai_chat_completions_non_streaming():
    manager = PluginManager()
    voice_jane = MockVoicePlugin("jane")
    manager.register_plugin(voice_jane)
    await manager.enable_plugin(voice_jane)

    server = HttpServer(manager, host="127.0.0.1", port=8992)
    app = server._app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "jane",
            "messages": [
                {"role": "system", "content": "You are Jane."},
                {"role": "user", "content": "¿Cómo estás?"},
            ],
            "stream": False,
        }
        resp = await client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        res_data = resp.json()

        assert res_data["object"] == "chat.completion"
        assert res_data["model"] == "jane"
        assert len(res_data["choices"]) == 1
        choice = res_data["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == "Hola desde Kateto."

        # Verify Voice received the prompt
        assert len(voice_jane.received_prompts) == 1
        assert "¿Cómo estás?" in voice_jane.received_prompts[0]

    await manager.close()


@pytest.mark.asyncio
async def test_openai_chat_completions_streaming_sse():
    manager = PluginManager()
    voice_doktor = MockVoicePlugin("doktor")
    manager.register_plugin(voice_doktor)
    await manager.enable_plugin(voice_doktor)

    server = HttpServer(manager, host="127.0.0.1", port=8993)
    app = server._app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "doktor",
            "messages": [{"role": "user", "content": "Explica tu plan."}],
            "stream": True,
        }
        resp = await client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        lines = resp.text.split("\n")
        sse_events = []
        for line in lines:
            if line.startswith("data: "):
                raw_data = line[6:].strip()
                if raw_data == "[DONE]":
                    sse_events.append("[DONE]")
                else:
                    sse_events.append(json.loads(raw_data))

        assert len(sse_events) >= 3
        assert sse_events[-1] == "[DONE]"

        # Rebuild streamed content
        tokens = []
        for ev in sse_events[:-1]:
            delta = ev["choices"][0]["delta"]
            if "content" in delta and delta["content"]:
                tokens.append(delta["content"])

        full_streamed = "".join(tokens)
        assert full_streamed == "Hola desde Kateto."

    await manager.close()


@pytest.mark.asyncio
async def test_openai_legacy_completions():
    manager = PluginManager()
    voice_jane = MockVoicePlugin("jane")
    manager.register_plugin(voice_jane)
    await manager.enable_plugin(voice_jane)

    server = HttpServer(manager, host="127.0.0.1", port=8994)
    app = server._app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "jane",
            "prompt": "Test legacy prompt",
            "stream": False,
        }
        resp = await client.post("/v1/completions", json=payload)
        assert resp.status_code == 200
        res_data = resp.json()
        assert res_data["choices"][0]["message"]["content"] == "Hola desde Kateto."

    await manager.close()
