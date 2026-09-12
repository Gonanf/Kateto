"""Todo-7 describe tests: window-batch describe call with text fallback.

Failing-first: `on_vision_describe_request` does not exist yet, so every
test here fails with AttributeError until the handler lands.
"""

from __future__ import annotations

import asyncio
import base64
import io
from types import SimpleNamespace

import openai
import pytest

from kateto.core.event import VisionDescribeRequestData, VisionDescribeResultData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor import static_vision_plugin as svp
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin


PRIMARY = "http://primary:8080/v1"
PRIMARY_MODEL = "test-vision-model"
FALLBACK = "http://fallback:8080/v1"


def _bad_request() -> openai.BadRequestError:
    import httpx

    request = httpx.Request("POST", "http://test/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"error": {"message": "no image support"}})
    return openai.BadRequestError("bad request", response=response, body=None)


def _timeout() -> openai.APITimeoutError:
    import httpx

    return openai.APITimeoutError(request=httpx.Request("POST", "http://test/v1/chat/completions"))


class _FakeCompletions:
    def __init__(self, endpoint: str | None, behavior: dict, calls: list) -> None:
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
        if action[0] == "timeout":
            raise _timeout()
        raise AssertionError(f"unknown fake action {action!r}")


class _FakeVisionClient:
    def __init__(self, endpoint: str | None, behavior: dict, calls: list) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(endpoint, behavior, calls))


def _install_fake_vision(monkeypatch: pytest.MonkeyPatch, behavior: dict, calls: list) -> None:
    def fake_openai_client(endpoint, api_key, retries, timeout):
        return _FakeVisionClient(endpoint, behavior, calls)

    monkeypatch.setattr(svp, "_openai_client", fake_openai_client)


class _FakeMCP:
    def __init__(self, result: str | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.seen: list = []

    async def try_call_tool(self, servers, tool, args):
        self.seen.append((servers, tool, args))
        if self.error is not None:
            raise self.error
        return self.result


def _install_fake_sidecar(monkeypatch: pytest.MonkeyPatch, mcp: _FakeMCP) -> None:
    monkeypatch.setattr(svp, "discovery_context_for", lambda plugins: SimpleNamespace(external_mcp=mcp))


class _ResultRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="result_recorder")
        self.seen: list[VisionDescribeResultData] = []

    async def on_vision_describe_result(self, data: VisionDescribeResultData) -> None:
        self.seen.append(data)


class _ErrorRecorder(Plugin):
    def __init__(self) -> None:
        from kateto.core.event import PluginErrorData

        super().__init__(name="error_recorder")
        self.seen: list[PluginErrorData] = []

    async def on_error(self, data) -> None:  # type: ignore[no-untyped-def]
        self.seen.append(data)


def _noise_frame(seed: int, size: tuple[int, int] = (48, 32)) -> bytes:
    import random

    from PIL import Image

    rng = random.Random(seed)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _make_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    """Enabled plugin with a neutered capture loop (no dummy-PNG races)."""
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


def _image_parts(call_kwargs: dict) -> list[dict]:
    content = call_kwargs["messages"][0]["content"]
    return [part for part in content if part.get("type") == "image_url"]


@pytest.mark.asyncio
async def test_describe_single_call_ordered_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 3 distinct frames + a primary client returning canned text
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    frames = [_noise_frame(seed) for seed in (1, 2, 3)]
    for i, payload in enumerate(frames):
        plugin._append_frame("screen", payload, 10.0 + i)

    # When: explicit screen describe with a correlation id
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen", correlation_id="c1")
    )
    await manager.wait_for_idle()

    # Then: exactly ONE call with 3 oldest→newest low-detail image parts
    assert len(calls) == 1
    endpoint, kwargs = calls[0]
    assert endpoint is PRIMARY
    parts = _image_parts(kwargs)
    assert len(parts) == 3
    for part, payload in zip(parts, frames):
        assert part["image_url"]["detail"] == "low"
        assert base64.b64encode(payload).decode() in part["image_url"]["url"]
    text_block = kwargs["messages"][0]["content"][0]["text"]
    assert "t+0.0s" in text_block and "t+2.0s" in text_block
    # And: one result echoing the correlation id
    assert len(results.seen) == 1
    result = results.seen[0]
    assert result.correlation_id == "c1"
    assert result.frame_count == 3 and result.kept_count == 3
    assert result.via == "primary" and result.source == "screen"
    assert result.window_start == 10.0 and result.window_end == 12.0
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_auto_fuses_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: both buffers filled
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    plugin._append_frame("screen", _noise_frame(11), 20.0)
    plugin._append_frame("screen", _noise_frame(12), 21.0)
    plugin._append_frame("webcam", _noise_frame(13), 22.0)

    # When: bare "look at this" (auto)
    await plugin.on_vision_describe_request(VisionDescribeRequestData(requester="jane"))
    await manager.wait_for_idle()

    # Then: one call per source, one fused result with labeled sections
    assert len(calls) == 2
    assert len(results.seen) == 1
    fused = results.seen[0].text
    assert "--- screen" in fused and "--- webcam" in fused
    assert results.seen[0].frame_count == 3
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_identical_frames_keep_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 3 identical frames
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)
    payload = _noise_frame(21)
    for i in range(3):
        plugin._append_frame("screen", payload, 30.0 + i)

    # When/Then: dedupe keeps the earliest only, call carries 1 part
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert len(_image_parts(calls[0][1])) == 1
    assert results.seen[0].frame_count == 3 and results.seen[0].kept_count == 1
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_primary_400_falls_back_to_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primary 400s, fallback endpoint configured and healthy
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("text", "fallback says")}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK, vision_fallback_model="vlm")
    plugin._append_frame("screen", _noise_frame(31), 40.0)
    plugin._append_frame("screen", _noise_frame(32), 41.0)

    # When/Then: ONE retry against the fallback with identical message shape
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    by_endpoint = [endpoint for endpoint, _ in calls]
    assert by_endpoint == [PRIMARY, FALLBACK]
    assert _image_parts(calls[0][1]) == _image_parts(calls[1][1])
    assert len(_image_parts(calls[1][1])) == 2
    assert results.seen[0].via == "fallback-vlm"
    assert "fallback says" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_sidecar_link(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primary 400s, sidecar answers
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",)}, calls)
    mcp = _FakeMCP(result="sidecar says")
    _install_fake_sidecar(monkeypatch, mcp)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK)
    plugin._append_frame("screen", _noise_frame(41), 50.0)

    # When/Then: sidecar wins, fallback HTTP never called
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert [endpoint for endpoint, _ in calls] == [PRIMARY]
    assert mcp.seen[0][0] == ["video_rag"] and mcp.seen[0][1] == "describe_images"
    assert results.seen[0].via == "sidecar"
    assert "sidecar says" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_sidecar_none_then_exception_fall_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primary 400s, sidecar returns None (absent tool)
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("text", "vlm says")}, calls)
    _install_fake_sidecar(monkeypatch, _FakeMCP(result=None))
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK)
    plugin._append_frame("screen", _noise_frame(51), 60.0)

    # When/Then: None falls through to the fallback link, never raises
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert results.seen[0].via == "fallback-vlm"
    await _teardown(manager, plugin.name, results.name)

    # Given: sidecar raising instead
    calls2: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("text", "vlm says")}, calls2)
    _install_fake_sidecar(monkeypatch, _FakeMCP(error=RuntimeError("sidecar down")))
    manager2 = PluginManager()
    results2 = _ResultRecorder()
    await manager2.enable_plugin(results2)
    plugin2 = await _make_plugin(manager2, vision_fallback_endpoint=FALLBACK)
    plugin2._append_frame("screen", _noise_frame(52), 61.0)

    # When/Then: exception also falls through, never raises
    await plugin2.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager2.wait_for_idle()
    assert results2.seen[0].via == "fallback-vlm"
    await _teardown(manager2, plugin2.name, results2.name)


@pytest.mark.asyncio
async def test_describe_both_400_recap(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: both HTTP links 400
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("400",), FALLBACK: ("400",)}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_fallback_endpoint=FALLBACK)
    plugin._append_frame("screen", _noise_frame(61), 70.0)

    # When/Then: recap result, no exception
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert results.seen[0].via == "recap"
    assert results.seen[0].text != ""
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_timeout_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: primary times out
    calls: list = []
    _install_fake_vision(monkeypatch, {PRIMARY: ("timeout",)}, calls)
    manager = PluginManager()
    errors = _ErrorRecorder()
    await manager.enable_plugin(errors)
    plugin = await _make_plugin(manager)
    plugin._append_frame("screen", _noise_frame(71), 80.0)
    request = VisionDescribeRequestData(requester="jane", source="screen")

    # When/Then: direct call raises (bus error path keeps the bus up)
    with pytest.raises(openai.APITimeoutError):
        await plugin.on_vision_describe_request(request)

    # And: the same failure through the bus surfaces as an error event, no crash
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    await manager.emit("vision_describe_request", request, source="probe")
    await manager.wait_for_idle()
    assert len(results.seen) == 0
    assert any(e.event_name == "vision_describe_request" for e in errors.seen)
    await _teardown(manager, plugin.name, errors.name, results.name)


@pytest.mark.asyncio
async def test_describe_unknown_source() -> None:
    # Given: an enabled plugin (no vision client needed — rejected before any call)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)

    # When/Then: error RESULT naming the valid sources, not an exception
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="projector")
    )
    await manager.wait_for_idle()
    assert len(results.seen) == 1
    assert "projector" in results.seen[0].text
    assert "auto" in results.seen[0].text and "screen" in results.seen[0].text
    assert "webcam" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_empty_window() -> None:
    # Given: empty buffers
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager)

    # When/Then: friendly empty text, zero counts
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert results.seen[0].text == "no frames captured yet"
    assert results.seen[0].frame_count == 0 and results.seen[0].kept_count == 0
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_registrations_have_receivers() -> None:
    # Given: an enabled plugin
    manager = PluginManager()
    plugin = await _make_plugin(manager)

    # When/Then: vision_describe_request is registered WITH receivers (voice-tool surface)
    regs = {reg.name: reg for reg in manager.get_event_registrations()}
    assert "vision_describe_request" in regs
    assert "static_vision" in regs["vision_describe_request"].receivers
    await _teardown(manager, plugin.name)


@pytest.mark.asyncio
async def test_describe_unconfigured_links_recap_names_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: NO endpoint/model anywhere, sidecar absent, frames present
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    _install_fake_sidecar(monkeypatch, _FakeMCP(result=None))
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(manager, vision_endpoint=None, vision_model=None)
    plugin._append_frame("screen", _noise_frame(81), 90.0)

    # When/Then: no HTTP link attempted, recap names the missing configuration
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert calls == []
    assert len(results.seen) == 1
    assert results.seen[0].via == "recap"
    assert "not configured" in results.seen[0].text
    assert "vision_endpoint/vision_model" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


@pytest.mark.asyncio
async def test_describe_endpoint_without_model_skips_both_http_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: endpoints set but NO model name anywhere (primary + fallback gates fail)
    calls: list = []
    _install_fake_vision(monkeypatch, {}, calls)
    manager = PluginManager()
    results = _ResultRecorder()
    await manager.enable_plugin(results)
    plugin = await _make_plugin(
        manager,
        vision_endpoint=PRIMARY,
        vision_model=None,
        vision_fallback_endpoint=FALLBACK,
        vision_fallback_model=None,
    )
    plugin._append_frame("screen", _noise_frame(82), 91.0)

    # When/Then: neither HTTP link attempted, recap without exception
    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="jane", source="screen")
    )
    await manager.wait_for_idle()
    assert calls == []
    assert results.seen[0].via == "recap"
    assert "not configured" in results.seen[0].text
    await _teardown(manager, plugin.name, results.name)


def test_describe_no_hardcoded_default_model() -> None:
    # The plan pins NO default model: every HTTP link needs an explicit model
    # name from settings, so the plugin source must not name one.
    from pathlib import Path

    source = Path(svp.__file__).read_text()
    assert "gpt-4o-mini" not in source
