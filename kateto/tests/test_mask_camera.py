"""MASK-4 tests: phone (POV) camera frames -> vision bus."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from kateto.core.event import VisionFrameData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.mask_camera import create_plugins
from kateto.plugins.mask_camera.camera_plugin import MaskCameraPlugin

# Minimal valid JPEG: SOI magic + payload (no real decoding happens here).
_JPEG = b"\xff\xd8" + b"\x00" * 32


class _FakeSettings(dict):
    """dict with attribute access — mirrors PluginSettings dual access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class _FrameRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__(name="frame_recorder")
        self.seen: list[VisionFrameData] = []

    async def on_vision_frame(self, data: VisionFrameData) -> None:
        self.seen.append(data)


def _settings(**kwargs: Any) -> _FakeSettings:
    return _FakeSettings(kwargs)


def _ctx(section: dict[str, Any] | None) -> Any:
    plugin: dict[str, Any] = {} if section is None else {"mask_camera": _FakeSettings(section)}
    return SimpleNamespace(config=SimpleNamespace(settings=SimpleNamespace(plugin=plugin)))


@pytest.mark.asyncio
async def test_submit_base64_valid_emits():
    # Given: an enabled plugin with a frame recorder on the bus
    manager = PluginManager()
    recorder = _FrameRecorder()
    await manager.enable_plugin(recorder)
    plugin = MaskCameraPlugin()
    await manager.enable_plugin(plugin)

    # When: a valid base64 JPEG is submitted
    payload = base64.b64encode(_JPEG).decode("ascii")
    ok = await plugin.submit_frame(payload)

    # Then: accepted, one event with the right source, buffer holds one frame
    await manager.wait_for_idle()
    assert ok is True
    assert len(recorder.seen) == 1
    assert recorder.seen[0].source == "mask_camera"
    assert recorder.seen[0].frame[:2] == b"\xff\xd8"
    assert plugin.stats()["buffer_frames"] == 1


@pytest.mark.asyncio
async def test_submit_data_url_prefix_accepted():
    # Given: an enabled plugin with a frame recorder on the bus
    manager = PluginManager()
    recorder = _FrameRecorder()
    await manager.enable_plugin(recorder)
    plugin = MaskCameraPlugin()
    await manager.enable_plugin(plugin)

    # When: a data-URL-wrapped base64 JPEG is submitted
    payload = "data:image/jpeg;base64," + base64.b64encode(_JPEG).decode("ascii")
    ok = await plugin.submit_frame(payload)

    # Then: the prefix is stripped and the frame is accepted
    await manager.wait_for_idle()
    assert ok is True
    assert len(recorder.seen) == 1


@pytest.mark.asyncio
async def test_submit_invalid_base64_dropped():
    # Given: an enabled plugin with a frame recorder on the bus
    manager = PluginManager()
    recorder = _FrameRecorder()
    await manager.enable_plugin(recorder)
    plugin = MaskCameraPlugin()
    await manager.enable_plugin(plugin)

    # When: garbage that is not base64 is submitted
    ok = await plugin.submit_frame("!!!not-base64!!!")

    # Then: rejected, invalid counter bumped, nothing emitted
    await manager.wait_for_idle()
    assert ok is False
    assert plugin.stats()["dropped_invalid"] == 1
    assert recorder.seen == []


@pytest.mark.asyncio
async def test_submit_non_jpeg_bytes_dropped():
    # Given: an enabled plugin
    manager = PluginManager()
    recorder = _FrameRecorder()
    await manager.enable_plugin(recorder)
    plugin = MaskCameraPlugin()
    await manager.enable_plugin(plugin)

    # When: raw bytes without JPEG magic are submitted
    before = plugin.stats()["dropped_invalid"]
    ok = await plugin.submit_frame(b"PNG\x89\x50\x4e\x47")

    # Then: rejected, invalid counter bumped
    await manager.wait_for_idle()
    assert ok is False
    assert plugin.stats()["dropped_invalid"] == before + 1


@pytest.mark.asyncio
async def test_submit_over_byte_cap_dropped():
    # Given: an enabled plugin with a tiny per-frame byte cap
    manager = PluginManager()
    recorder = _FrameRecorder()
    await manager.enable_plugin(recorder)
    plugin = MaskCameraPlugin(settings=_settings(camera_frame_byte_cap=10))
    await manager.enable_plugin(plugin)

    # When: a frame larger than the cap is submitted
    before = plugin.stats()["dropped_invalid"]
    ok = await plugin.submit_frame(b"\xff\xd8" + b"x" * 64)

    # Then: rejected, invalid counter bumped
    await manager.wait_for_idle()
    assert ok is False
    assert plugin.stats()["dropped_invalid"] == before + 1


@pytest.mark.asyncio
async def test_submit_rate_gate_drops_excess():
    # Given: an enabled plugin capped at 2 fps
    manager = PluginManager()
    plugin = MaskCameraPlugin(settings=_settings(camera_max_fps=2.0))
    await manager.enable_plugin(plugin)

    # When: six frames arrive 0.05s apart (well under the 0.5s floor)
    for i in range(6):
        await plugin.submit_frame(_JPEG, ts=1000.0 + i * 0.05)

    # Then: at most the first couple are accepted, the rest are rate-dropped
    stats = plugin.stats()
    assert stats["frames_emitted"] <= 2
    assert stats["dropped_rate"] > 0


@pytest.mark.asyncio
async def test_ring_buffer_bounded():
    # Given: an enabled plugin with a 5-frame buffer at 1 fps
    manager = PluginManager()
    plugin = MaskCameraPlugin(settings=_settings(camera_buffer_frames=5, camera_max_fps=1.0))
    await manager.enable_plugin(plugin)

    # When: eight frames arrive spaced past the rate floor
    for i in range(8):
        await plugin.submit_frame(_JPEG, ts=1000.0 + i * 1.1)

    # Then: only the last five survive and the newest is the latest accepted
    assert len(plugin.frame_window(3600.0)) == 5
    latest = plugin.latest_frame()
    assert latest is not None
    assert latest.ts == pytest.approx(1000.0 + 7 * 1.1)


@pytest.mark.asyncio
async def test_frame_window_filters_by_ts():
    # Given: an enabled plugin at a high fps floor
    manager = PluginManager()
    plugin = MaskCameraPlugin(settings=_settings(camera_max_fps=100.0))
    await manager.enable_plugin(plugin)

    # When: three frames arrive 1s apart
    for i in range(3):
        await plugin.submit_frame(_JPEG, ts=1000.0 + i)

    # Then: a 1.5s window keeps only the two newest frames
    window = plugin.frame_window(1.5)
    assert len(window) == 2
    assert 1000.0 not in [frame.ts for frame in window]
    assert len(plugin.frame_window(3600.0)) == 3


def test_create_plugins_without_section_creates_inert_plugin():
    # Given: no [plugin.mask_camera] section
    # When: plugins are discovered
    plugins = create_plugins(_ctx(None))
    # Then: the plugin is created (inert until fed frames)
    assert len(plugins) == 1
    assert isinstance(plugins[0], MaskCameraPlugin)


def test_create_plugins_disabled_section_skips():
    # Given: a section with enabled=false
    # When: plugins are discovered
    # Then: no plugin is created
    assert create_plugins(_ctx({"enabled": False})) == ()


def test_create_plugins_enabled_section_creates_plugin():
    # Given: a section with enabled=true
    # When: plugins are discovered
    plugins = create_plugins(_ctx({"enabled": True}))
    # Then: the plugin is created
    assert len(plugins) == 1
    assert isinstance(plugins[0], MaskCameraPlugin)


@pytest.mark.asyncio
async def test_submit_frame_without_manager_returns_false():
    # Given: a plugin never enabled (no manager, not enabled)
    plugin = MaskCameraPlugin()

    # When: a frame is submitted
    ok = await plugin.submit_frame(_JPEG)

    # Then: rejected without raising, disabled counter bumped
    assert ok is False
    assert plugin.stats()["dropped_disabled"] == 1
