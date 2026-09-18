"""Describe lento, frames pesados y prewarm: el timeout de 30 s no alcanza.

Cubre el bug 120: un frame nativo de 1920x1080 cuesta ~2350 tokens de visión
y el prefill va a ~66 tok/s (~36 s), así que el `wait_for(..., 30.0)` del
cliente MCP corta siempre. La visión pasa su propio timeout (vision_timeout
con piso de 120 s), recomprime antes de mandar (ancho 1024, cap ~1.5MB del
sidecar), manda 2 frames por describe (el más viejo y el más nuevo) y
precalienta el VLM al arrancar la periódica.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
from types import SimpleNamespace

import pytest
from loguru import logger

from kateto.core.event import VisionDescribeRequestData, VisionDescribeResultData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import (
    StaticVisionPlugin,
    _cap_frames,
    _compress_for_sidecar,
    _data_url,
)


class _CapturingMCP:
    """Fake sidecar con try_call_tool_result que captura timeout e imágenes."""

    def __init__(self, text: str = "sidecar saw it", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.seen: list = []

    async def try_call_tool_result(self, servers, tool, args, timeout: float = 30.0):
        self.seen.append({"servers": servers, "tool": tool, "args": args, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text, is_error=False, server="video_rag", tool=tool)


def _install_sidecar(monkeypatch: pytest.MonkeyPatch, mcp: _CapturingMCP) -> None:
    monkeypatch.setattr(
        svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp)
    )


class _ResultRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="result_recorder")
        self.seen: list[VisionDescribeResultData] = []

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self.seen.append(data)


def _noise_frame(seed: int, size: tuple[int, int] = (48, 32)) -> bytes:
    import random

    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", size)
    px = img.load()
    assert px is not None
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _big_frame() -> bytes:
    """Un frame sintético de 1920x1080 que pesa (ruido RGB sin comprimir)."""
    from PIL import Image

    img = Image.frombytes("RGB", (1920, 1080), os.urandom(1920 * 1080 * 3))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    """Plugin sin endpoint (va directo al sidecar) y sin captura real."""
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = kwargs.pop("vision_endpoint", None)
    plugin.vision_model = kwargs.pop("vision_model", None)
    for key, value in kwargs.items():
        setattr(plugin, key, value)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._windows.clear()
    plugin._dropped.clear()
    return plugin


async def _teardown(manager: PluginManager, *names: str) -> None:
    for name in names:
        await asyncio.wait_for(manager.disable_plugin(name), timeout=5.0)


def _decode_data_url(url: str) -> bytes:
    return base64.b64decode(url.split(",", 1)[1])


@pytest.mark.asyncio
async def test_vision_passes_configured_timeout_floored_at_120(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: vision_timeout=45 (el default histórico de 60 también cae acá)
    mcp = _CapturingMCP()
    _install_sidecar(monkeypatch, mcp)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_timeout=45.0)
    plugin._append_frame("screen", _noise_frame(1), 10.0)
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="INFO")
    try:
        # When: describe por el sidecar
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()
    finally:
        logger.remove(handler_id)

    # Then: el timeout que viaja no es el 30 s fijo sino max(45, 120), logueado
    assert len(mcp.seen) == 1
    assert mcp.seen[0]["timeout"] == 120.0
    assert results.seen[0].via == "sidecar"
    joined = "\n".join(messages)
    assert "with timeout 120" in joined
    assert "1 frame(s)" in joined
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_vision_timeout_above_floor_travels_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: vision_timeout=200 (frío extremo del VLM, configurado a mano)
    mcp = _CapturingMCP()
    _install_sidecar(monkeypatch, mcp)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_timeout=200.0)
    plugin._append_frame("screen", _noise_frame(2), 20.0)

    # When:
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()

    # Then: viaja el configurado, sin recorte
    assert mcp.seen[0]["timeout"] == 200.0
    assert results.seen[0].via == "sidecar"
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_big_frame_gets_recompressed_before_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: un frame sintético de 1920x1080
    original = _big_frame()
    assert len(_data_url(original)) > 1_500_000
    mcp = _CapturingMCP()
    _install_sidecar(monkeypatch, mcp)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    plugin._append_frame("screen", original, 30.0)

    # When: describe por el sidecar
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()

    # Then: lo que viaja es más chico que el original, válido y acotado
    sent = mcp.seen[0]["args"]["images"]
    assert len(sent) == 1
    assert len(sent[0]) < len(_data_url(original))
    assert len(sent[0]) <= 1_500_000
    from PIL import Image

    with Image.open(io.BytesIO(_decode_data_url(sent[0]))) as img:
        assert img.size[0] <= 1024
        assert img.size[0] / img.size[1] == pytest.approx(1920 / 1080, rel=0.01)
    assert results.seen[0].via == "sidecar"
    await _teardown(manager, plugin.name, results.name)


def test_small_frame_passes_through_untouched() -> None:
    # Given: un frame chico (48x32)
    tiny = _noise_frame(3)

    # When: compresión para el sidecar
    out = _compress_for_sidecar(tiny, max_width=1024)

    # Then: mismos bytes, sin reencode al pedo
    assert out == tiny


def test_cap_frames_keeps_oldest_and_newest() -> None:
    # Given: 3 frames distintos ya dedupados
    kept = [(10.0, b"a"), (11.0, b"b"), (12.0, b"c")]

    # When/Then: cap 2 → el más viejo y el más nuevo (lo que muestra el cambio)
    assert _cap_frames(kept, 2) == [(10.0, b"a"), (12.0, b"c")]
    # And: sin cap o con cap holgado → todo
    assert _cap_frames(kept, 0) == kept
    assert _cap_frames(kept, 5) == kept
    # And: cap 1 → el más nuevo
    assert _cap_frames(kept, 1) == [(12.0, b"c")]


@pytest.mark.asyncio
async def test_describe_sends_oldest_and_newest_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 3 frames distintos con el default (cap 2)
    mcp = _CapturingMCP()
    _install_sidecar(monkeypatch, mcp)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    frames = [_noise_frame(seed) for seed in (11, 12, 13)]
    for i, payload in enumerate(frames):
        plugin._append_frame("screen", payload, 40.0 + i)

    # When:
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()

    # Then: viajan 2 (el más viejo y el más nuevo), el conteo queda en el result
    sent = mcp.seen[0]["args"]["images"]
    assert sent == [_data_url(frames[0]), _data_url(frames[2])]
    assert results.seen[0].kept_count == 2
    assert results.seen[0].frame_count == 3
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_prewarm_failure_never_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: endpoint configurado pero muerto + sidecar que explota
    manager = PluginManager()
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = "http://dead:8080/v1"
    plugin.vision_model = "vlm"
    plugin._PREWARM_DELAY_SECS = 0.0
    monkeypatch.setattr(
        svp, "_openai_client", lambda *args: (_ for _ in ()).throw(RuntimeError("VLM down"))
    )
    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        # When: el prewarm corre contra todo roto
        await plugin._prewarm_vlm()
    finally:
        logger.remove(handler_id)

    # Then: no levanta, sólo loguea (nada que narrar, ningún error en el bus)
    joined = "\n".join(messages)
    assert "prewarm failed" in joined

    # Given: sin endpoint y sidecar que explota
    boom = _CapturingMCP(error=RuntimeError("sidecar down"))
    _install_sidecar(monkeypatch, boom)
    plugin.vision_endpoint = None
    plugin.vision_model = None
    messages2: list[str] = []
    handler_id2 = logger.add(messages2.append, format="{message}", level="WARNING")
    try:
        # When:
        await plugin._prewarm_vlm()
    finally:
        logger.remove(handler_id2)

    # Then: tampoco rompe
    assert "prewarm failed" in "\n".join(messages2)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)


@pytest.mark.asyncio
async def test_prewarm_spawns_on_enable_and_finishes_clean() -> None:
    # Given: plugin con periódica pero sin ningún link VLM
    manager = PluginManager()
    plugin = StaticVisionPlugin(
        opted_in=(("jane", "30s"),), capture_fps=20.0, config_dir=None
    )
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin._PREWARM_DELAY_SECS = 0.01

    # When: enable
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    for _ in range(200):
        if plugin._prewarm_task is not None and plugin._prewarm_task.done():
            break
        await asyncio.sleep(0.02)

    # Then: la tarea terminó sola y sin excepción (skip sin link, best-effort)
    assert plugin._prewarm_task is not None and plugin._prewarm_task.done()
    assert plugin._prewarm_task.exception() is None
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
