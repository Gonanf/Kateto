"""Precedencia visible de config por voz + silencio del recap periodico + motivo del sidecar.

Cubre el bug 115: el archivo voices/<voz>/config.toml pisa al [voice] del
principal en silencio, el recap hacia hablar a la voz cada 30 s, y el
"sidecar unreachable" mezclaba dos causas.
"""

from __future__ import annotations

import asyncio
import io
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from kateto.core.config import (
    McpServerSettings,
    get_voice_file_sources,
    get_voice_override_notes,
    load_config,
)
from kateto.core.event import VisionDescribeRequestData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin
from kateto.plugins.system.external_mcp import ExternalMcpManager

_MINIMAL_CONFIG = """\
[kateto]
debug = false

[cli]
allowlist = ["ls"]

[voice.jane]
vision_periodic = false
skills = ["orchestrator"]
"""


def _noise_frame(seed: int) -> bytes:
    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", (48, 32))
    px = img.load()
    assert px is not None
    for y in range(32):
        for x in range(48):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeMCP:
    def __init__(self, result: str | None = None) -> None:
        self.result = result

    async def try_call_tool(self, servers, tool, args):
        return self.result


class _GenerateRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="generate_recorder")
        self.seen: list = []

    async def on_generate(self, data) -> None:  # type: ignore[no-untyped-def]
        self.seen.append(data)


def test_voice_folder_override_is_logged_with_both_values_and_winner(tmp_path: Path) -> None:
    # Given: el principal dice vision_periodic=false, el archivo por voz dice true
    config_dir = tmp_path / "kateto"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(_MINIMAL_CONFIG, encoding="utf-8")
    voice_dir = config_dir / "voices" / "jane"
    voice_dir.mkdir(parents=True)
    (voice_dir / "config.toml").write_text("vision_periodic = true\n", encoding="utf-8")

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        # When: carga la config
        loaded = load_config(config_dir=config_dir)
    finally:
        logger.remove(handler_id)

    # Then: el valor efectivo sigue siendo el del archivo por voz (sin cambio semantico)
    assert loaded.settings.voice["jane"].get("vision_periodic") is True
    # And: el aviso nombra clave, ambos valores y el archivo ganador
    notes = [n for n in get_voice_override_notes() if n["voice"] == "jane" and n["key"] == "vision_periodic"]
    assert len(notes) == 1
    assert notes[0]["principal"] is False
    assert notes[0]["file_value"] is True
    assert "voices" in notes[0]["winner"] and "jane" in notes[0]["winner"]
    joined = "\n".join(messages)
    assert "voice.jane.vision_periodic" in joined
    assert "False" in joined and "True" in joined
    # And: la fuente queda registrada para `config check`
    assert "vision_periodic" in get_voice_file_sources()["jane"]


@pytest.mark.asyncio
async def test_periodic_recap_stays_silent_and_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: sin VLM y sin sidecar (todo cae al recap), un frame en ventana
    monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=_FakeMCP(None)))
    manager = PluginManager()
    generates = _GenerateRecorder()
    await manager.enable_plugin(generates)
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = None
    plugin.vision_model = None
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._append_frame("screen", _noise_frame(1), 10.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        # When: dos ticks periodicos con recap
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="scheduler:jane", source="screen")
        )
        await manager.wait_for_idle()
    finally:
        logger.remove(handler_id)
        manager.remove_event_observer(envelopes.append)

    # Then: ningun generate periodico, y un solo warning
    assert [e for e in envelopes if e.name == "generate"] == []
    assert len([m for m in messages if "periodic narration suppressed" in m]) == 1
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(generates.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_real_describe_still_narrates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: un VLM primario que responde de verdad
    async def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="a cat on a desk"))])

    monkeypatch.setattr(
        svp, "_openai_client", lambda *args: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )
    manager = PluginManager()
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = "http://primary:8080/v1"
    plugin.vision_model = "vlm"
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._append_frame("screen", _noise_frame(2), 20.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: tick periodico con descripcion real
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: la narracion periodica sigue como estaba
    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 1
    assert generates[0].target == "jane"
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)


@pytest.mark.asyncio
async def test_user_ask_recap_still_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: sin backend (recap) pero pedido directo del usuario
    from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin as SVP

    monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=_FakeMCP(None)))
    manager = PluginManager()
    results: list = []

    class _Results(Plugin):
        def __init__(self) -> None:
            super().__init__(name="results")

        async def on_vision_describe_result(self, data) -> None:  # type: ignore[no-untyped-def]
            results.append(data)

    await manager.enable_plugin(_Results())
    plugin = SVP(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = None
    plugin.vision_model = None
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._append_frame("screen", _noise_frame(3), 30.0)

    # When: pregunta del usuario (no scheduler)
    await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane", source="screen"))
    await manager.wait_for_idle()

    # Then: contesta que no pudo ver (eso es una respuesta, no narracion sola)
    assert len(results) == 1
    assert results[0].via == "recap"
    assert results[0].text != ""
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)


def test_sidecar_reason_distinguishes_no_client_vs_dead_client() -> None:
    # Given: un manager sin clientes y otro con cliente caido
    empty = ExternalMcpManager()
    dead = ExternalMcpManager()
    dead.configure("op", "video_rag", McpServerSettings(command="not-a-real-process", args=[]))

    # When: se pregunta por que no se puede llamar
    no_client = empty.sidecar_reason(["video_rag"], "describe_images")

    # Then: sin cliente configurado se dice explicito
    assert "no client configured" in no_client

    # And: un stub corriendo sin la tool cae en la otra rama
    running = ExternalMcpManager()
    running._clients["video_rag"] = SimpleNamespace(is_running=True, last_error=None)
    assert "no 'describe_images' tool" in running.sidecar_reason(["video_rag"], "describe_images")


@pytest.mark.asyncio
async def test_fallback_logs_distinct_reasons_for_each_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: plugin sin VLM; caso 1: manager vacio, caso 2: cliente caido real
    sections = [
        ("screen", [(1.0, b"x")], 1, "p", [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,xx"}}])
    ]
    content: list = [{"type": "text", "text": "p"}] + [p for _, _, _, _, parts in sections for p in parts]

    async def run_case(mcp) -> str:
        monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp))
        plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
        messages: list[str] = []
        handler_id = logger.add(messages.append, format="{message}", level="WARNING")
        try:
            await plugin._describe_fallback("p", content, {}, sections)
        finally:
            logger.remove(handler_id)
        return "\n".join(messages)

    empty = ExternalMcpManager()
    dead = ExternalMcpManager()
    dead.configure("op", "video_rag", McpServerSettings(command="not-a-real-process", args=[]))
    await asyncio.wait_for(dead.start_all(), timeout=60.0)
    try:
        logged_empty = await run_case(empty)
        logged_dead = await run_case(dead)
    finally:
        await dead.stop_all()

    # Then: los dos motivos se distinguen en el log
    assert "sidecar video_rag unreachable" in logged_empty
    assert "no client configured" in logged_empty
    assert "sidecar video_rag unreachable" in logged_dead
    assert "not running" in logged_dead
