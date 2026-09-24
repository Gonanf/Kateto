import httpx
import pytest

from kateto.core.event import GenerateData, TranscriptionData, VisualExplanationData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin
from kateto.voices.tools import build_event_tools

VALID_EXPLANATION = {
    "voice_id": "jane",
    "kind": "mermaid",
    "title": "Pipeline",
    "code": "flowchart LR\nA-->B",
    "msg_ref": "trace-123",
}


def test_visual_explanation_contract_accepts_valid_payload():
    data = VisualExplanationData.model_validate(VALID_EXPLANATION)
    assert data.voice_id == "jane"
    assert data.kind == "mermaid"
    assert data.title == "Pipeline"
    assert data.code == VALID_EXPLANATION["code"]
    assert data.msg_ref == "trace-123"


def test_visual_explanation_contract_minimal_payload():
    # Given: solo los campos requeridos (voice_id, code)
    data = VisualExplanationData.model_validate({"voice_id": "doktor", "code": "graph TD; A-->B"})
    assert data.kind == "mermaid"
    assert data.title == ""
    assert data.msg_ref is None


def test_visual_explanation_contract_rejects_extra_field():
    # Given: un campo desconocido (EventModel es strict + extra="forbid")
    with pytest.raises(ValueError):
        VisualExplanationData.model_validate({**VALID_EXPLANATION, "bogus": 1})


@pytest.mark.asyncio
async def test_visual_explanation_registered_with_receiver():
    # Given: visual_overlay habilitado en el manager
    manager = PluginManager()
    plugin = VisualOverlayPlugin()
    await manager.enable_plugin(plugin)
    try:
        # Then: el evento está registrado con su contrato y el receiver visual_overlay
        registrations = {r.name: r for r in manager.get_event_registrations()}
        assert "visual_explanation" in registrations
        reg = registrations["visual_explanation"]
        assert reg.contract is VisualExplanationData
        assert "visual_overlay" in reg.receivers
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_build_event_tools_exposes_visual_explanation():
    # Given: visual_overlay habilitado (único receiver del evento)
    manager = PluginManager()
    plugin = VisualOverlayPlugin()
    await manager.enable_plugin(plugin)
    try:
        # When: se construyen las tools de voz
        tools = {t["function"]["name"]: t for t in build_event_tools(manager)}
        # Then: visual_explanation está expuesta con los campos requeridos
        assert "visual_explanation" in tools
        function = tools["visual_explanation"]["function"]
        params = function.get("parameters") or {}
        required = params.get("required") or []
        assert isinstance(required, list)
        assert "code" in required
        assert "voice_id" in required
        # kind/title/msg_ref tienen default -> no requeridos
        assert "kind" not in required
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_build_event_tools_skips_visual_explanation_without_receiver():
    # Given: un manager vacío (evento nunca registrado)
    manager = PluginManager()
    # When: se construyen las tools
    tools = {t["function"]["name"] for t in build_event_tools(manager)}
    # Then: no aparece la tool (sin receiver el evento no se expone, tools.py:558)
    assert "visual_explanation" not in tools


@pytest.mark.asyncio
async def test_visual_explanation_roundtrip_emit_to_receiver_and_observer():
    manager = PluginManager()
    plugin = VisualOverlayPlugin()
    await manager.enable_plugin(plugin)
    observed = []
    manager.add_event_observer(lambda env: observed.append(env))
    try:
        # When: se emite visual_explanation (como lo haría una voz vía tool)
        await manager.emit(
            "visual_explanation",
            VisualExplanationData.model_validate(VALID_EXPLANATION),
            source="jane",
        )
        await manager.wait_for_idle()
        # Then: el receiver guardó el último y el observer vio el payload exacto
        assert plugin._last_explanation == VALID_EXPLANATION
        assert len(observed) == 1
        envelope = observed[0]
        assert envelope.name == "visual_explanation"
        assert envelope.source == "jane"
        assert envelope.data.model_dump() == VALID_EXPLANATION
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_discussion_route_serves_html_no_store():
    # Given: el HttpServer levantado
    manager = PluginManager()
    server = HttpServer(manager, host="127.0.0.1", port=8896)
    await server.start()
    try:
        # When: GET /discussion
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8896/discussion")
        # Then: 200, text/html, sin cache
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "no-store" in resp.headers.get("cache-control", "")
        assert "Kateto · Discusión" in resp.text
    finally:
        await server.stop()


class FixtureVoice(Plugin):
    """Voz de prueba: captura los generate que le llegan."""

    def __init__(self, name: str = "jane") -> None:
        super().__init__(name, capabilities=("voice",))
        self.generates: list[GenerateData] = []

    async def on_generate(self, data: GenerateData) -> None:
        self.generates.append(data)


@pytest.mark.asyncio
async def test_send_event_transcription_and_generate_targeted():
    # Given: contratos registrados + una voz jane habilitada
    manager = PluginManager()
    manager.register_event("transcription", TranscriptionData)
    manager.register_event("generate", GenerateData)
    voice = FixtureVoice("jane")
    await manager.enable_plugin(voice)
    server = HttpServer(manager, host="127.0.0.1", port=8995)
    await server.start()
    try:
        async with httpx.AsyncClient() as client:
            # When: transcription (modo auto) -> clasificador/voz ponderada
            resp = await client.post(
                "http://127.0.0.1:8995/events/send",
                json={"event_name": "transcription", "data": {"text": "hola"}},
            )
            # Then: aceptado
            assert resp.json() == {"status": "ok"}

            # When: generate directo a jane con origin external
            resp = await client.post(
                "http://127.0.0.1:8995/events/send",
                json={
                    "event_name": "generate",
                    "data": {"prompt": "explicame el pipeline", "origin": "external"},
                    "target": "jane",
                },
            )
            assert resp.json() == {"status": "ok"}
            await manager.wait_for_idle()

            # Then: generate llegó SOLO a jane con origin external
            assert len(voice.generates) == 1
            gen = voice.generates[0]
            assert gen.prompt == "explicame el pipeline"
            assert gen.origin == "external"

            # When: generate a una voz inexistente
            resp = await client.post(
                "http://127.0.0.1:8995/events/send",
                json={
                    "event_name": "generate",
                    "data": {"prompt": "a nadie"},
                    "target": "ghost",
                },
            )
            assert resp.json() == {"status": "ok"}  # lo acepta el contrato; no hay receiver

            # When: evento desconocido -> error visible
            resp = await client.post(
                "http://127.0.0.1:8995/events/send",
                json={"event_name": "no_such_event", "data": {}},
            )
            assert resp.json()["error"] == "unknown event: no_such_event"
    finally:
        await server.stop()