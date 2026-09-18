"""Ventana real en el describe de visión + error del sidecar no narrado.

Cubre el bug 116: con la escena quieta el dedupe deja 1 kept y el span salía
de los kept (0s); además el texto de error del sidecar se narraba como si
fuera la descripción.
"""

from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from loguru import logger

from kateto.core.event import VisionDescribeRequestData, VisionDescribeResultData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import (
    StaticVisionPlugin,
    _is_sidecar_error,
    _window_span,
)

PRIMARY = "http://primary:8080/v1"
PRIMARY_MODEL = "test-vision-model"
FALLBACK = "http://fallback:8080/v1"
SIDECAR_ERROR = (
    "video-rag describe_images: VLM unreachable at http://127.0.0.1:8093 "
    "(model qwen3-vl)"
)


def _bad_request():
    import httpx

    import openai

    request = httpx.Request("POST", "http://test/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": "no image support"}})
    return openai.BadRequestError("bad request", response=response, body=None)


class _FakeCompletions:
    def __init__(self, endpoint, behavior, calls) -> None:
        self._endpoint = endpoint
        self._behavior = behavior
        self._calls = calls

    async def create(self, **kwargs):
        self._calls.append((self._endpoint, kwargs))
        action = self._behavior.get(self._endpoint, ("text", "described"))
        if action[0] == "text":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=action[1]))])
        if action[0] == "400":
            raise _bad_request()
        raise AssertionError(f"unknown fake action {action!r}")


class _FakeVisionClient:
    def __init__(self, endpoint, behavior, calls) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(endpoint, behavior, calls))


def _install_fake_vision(monkeypatch: pytest.MonkeyPatch, behavior: dict, calls: list) -> None:
    def fake_openai_client(endpoint, api_key, retries, timeout):
        return _FakeVisionClient(endpoint, behavior, calls)

    monkeypatch.setattr(svp, "_openai_client", fake_openai_client)


class _FakeMCP:
    def __init__(self, result: str | None = None) -> None:
        self.result = result

    async def try_call_tool(self, servers, tool, args):
        return self.result


def _install_fake_sidecar(monkeypatch: pytest.MonkeyPatch, mcp: _FakeMCP) -> None:
    monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp))


class _ResultRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="result_recorder")
        self.seen: list[VisionDescribeResultData] = []

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self.seen.append(data)


def _noise_frame(seed: int) -> bytes:
    import random

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


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    """Enabled plugin with a neutered capture loop (deterministic buffers)."""
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    plugin.vision_endpoint = kwargs.pop("vision_endpoint", PRIMARY)
    plugin.vision_model = kwargs.pop("vision_model", PRIMARY_MODEL)
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


def test_window_span_helpers() -> None:
    # Given: full frames + their deduped subset and the asked window
    frames = [(10.0, b"a"), (11.0, b"b"), (12.0, b"c")]
    # When/Then: several kept -> the capture range, never the asked window
    assert _window_span(frames, frames, 5.0) == 12.0 - 10.0
    # And: a single kept (still scene) -> the asked window, never 0
    assert _window_span(frames, [frames[0]], 5.0) == 5.0
    # And: a lone frame in the deque -> the asked window too
    assert _window_span([(42.0, b"a")], [(42.0, b"a")], 5.0) == 5.0


def test_is_sidecar_error_markers() -> None:
    # Given/When/Then: error shapes are errors, prose is not
    assert _is_sidecar_error(SIDECAR_ERROR)
    assert _is_sidecar_error('{"error": "MCP tool timed out: describe_images"}')
    assert not _is_sidecar_error("a quiet PDF page on screen")
    assert not _is_sidecar_error("")


@pytest.mark.asyncio
async def test_static_scene_reports_window_not_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 5 identical frames (still PDF) with a healthy primary
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    payload = _noise_frame(7)
    for i in range(5):
        plugin._append_frame("screen", payload, 10.0 + i)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: the periodic tick describes
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="auto")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: one kept out of five, but the span is the asked window (5s, not 0)
    assert len(results.seen) == 1
    result = results.seen[0]
    assert result.kept_count == 1 and result.frame_count == 5
    assert result.window_end - result.window_start == 5.0
    assert "(5s, 1/5 frames)" in result.text
    # And: the narration prompt says 5s with the frame note, never 0s
    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 1
    assert generates[0].data.prompt.startswith("[look-at auto 5s, 1 frame]:")
    assert "0s" not in generates[0].data.prompt.split("]:", 1)[0]
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_moving_scene_span_matches_capture_range(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 3 distinct frames over 2s with a healthy primary
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    for i, seed in enumerate((11, 12, 13)):
        plugin._append_frame("screen", _noise_frame(seed), 10.0 + i)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: the periodic tick describes
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: the span is the real capture range, no frame note needed
    assert results.seen[0].window_start == 10.0
    assert results.seen[0].window_end == 12.0
    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 1
    assert generates[0].data.prompt.startswith("[look-at screen 2s]:")
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_single_frame_uses_asked_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a single frame in the deque with a healthy primary
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    plugin._append_frame("screen", _noise_frame(21), 42.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: the periodic tick describes
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: span is the asked window (5s), not 0
    assert results.seen[0].window_end - results.seen[0].window_start == 5.0
    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 1
    assert generates[0].data.prompt.startswith("[look-at screen 5s, 1 frame]:")
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_request_window_secs_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a still scene (one kept) and a request asking for 9s
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    payload = _noise_frame(31)
    for i in range(3):
        plugin._append_frame("screen", payload, 20.0 + i)

    # When: the request overrides the window
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen", window_secs=9.0)
    )
    await manager.wait_for_idle()

    # Then: the asked window wins over the plugin default
    assert results.seen[0].kept_count == 1
    assert results.seen[0].window_end - results.seen[0].window_start == 9.0
    assert "(9s, 1/3 frames)" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_sidecar_error_falls_through_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primary 400s, sidecar answering ERROR text, healthy fallback
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("text", "fallback says")}, calls)
    _install_fake_sidecar(monkeypatch, _FakeMCP(result=SIDECAR_ERROR))
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK, vision_fallback_model="vlm")
    plugin._append_frame("screen", _noise_frame(41), 50.0)

    messages: list[str] = []
    handler_id = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        # When: describing
        await plugin.on_vision_describe_request(
            VisionDescribeRequestData(requester="jane", source="screen")
        )
        await manager.wait_for_idle()
    finally:
        logger.remove(handler_id)

    # Then: the error text is NOT the description — the fallback answers
    assert len(results.seen) == 1
    assert results.seen[0].via == "fallback-vlm"
    assert "fallback says" in results.seen[0].text
    assert "VLM unreachable" not in results.seen[0].text
    # And: the full reason (endpoint + model) is logged once, diagnosable
    joined = "\n".join(messages)
    assert "not a description" in joined
    assert "http://127.0.0.1:8093" in joined and "qwen3-vl" in joined
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_sidecar_error_without_fallback_recaps_and_stays_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: primary 400s, sidecar error text, no fallback link
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",)}, calls)
    _install_fake_sidecar(monkeypatch, _FakeMCP(result=SIDECAR_ERROR))
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=None, vision_fallback_model=None)
    plugin._append_frame("screen", _noise_frame(51), 60.0)
    envelopes: list = []
    manager.add_event_observer(envelopes.append)

    # When: a periodic tick AND a direct user ask describe
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    manager.remove_event_observer(envelopes.append)

    # Then: both are recaps naming the sidecar failure (a "could not see" answer)
    assert len(results.seen) == 2
    assert all(r.via == "recap" for r in results.seen)
    assert all("VLM unreachable at http://127.0.0.1:8093" in r.text for r in results.seen)
    # And: the ambient narration never voices the error as what it saw
    assert [e for e in envelopes if e.name == "generate"] == []
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_sidecar_timeout_json_is_error_not_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: primary 400s, sidecar answering our own client timeout JSON
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("text", "vlm says")}, calls)
    _install_fake_sidecar(
        monkeypatch, _FakeMCP(result='{"error": "MCP tool timed out: describe_images"}')
    )
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK, vision_fallback_model="vlm")
    plugin._append_frame("screen", _noise_frame(61), 70.0)

    # When/Then: the JSON error falls through, never narrated as seen
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert results.seen[0].via == "fallback-vlm"
    assert "timed out" not in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)
