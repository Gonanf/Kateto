"""Static vision plugin tests with tmp_path isolation (plan todo 10).

Each test builds a fresh PluginManager plus a tmp bootstrapped config, so no
test touches the real user config dir and no state leaks between tests (fresh
manager per test; PluginManager carries no module-global registry).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kateto.core.config import default_config_dir, load_config
from kateto.core.event import VisionFrameData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin


def _isolated_config_dir(tmp_path: Path) -> Path:
    """Bootstrap a throwaway config; writes land in tmp_path only."""
    config_dir = tmp_path / "kateto"
    loaded = load_config(config_dir=config_dir, defaults_dir=default_config_dir())
    return loaded.paths.config_dir


class FrameListenerPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="frame_listener")
        self.received: list[VisionFrameData] = []

    async def on_vision_frame(self, data: VisionFrameData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_static_vision_plugin_enable_and_trigger(tmp_path: Path):
    # Given: an isolated config dir plus a fresh manager (no shared singleton).
    config_dir = _isolated_config_dir(tmp_path)
    manager = PluginManager()
    assert "vision_describe_request" not in {
        reg.name for reg in manager.get_event_registrations()
    }
    plugin = StaticVisionPlugin(interval_seconds=5.0, dept="fun", config_dir=config_dir)

    listener = FrameListenerPlugin()
    await manager.enable_plugin(listener)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Then: the voice-tool surface is registered WITH receivers once enabled.
    regs = {reg.name: reg for reg in manager.get_event_registrations()}
    assert regs["vision_describe_request"].receivers == ("static_vision",)

    # When: a capture is triggered manually.
    await plugin.on_vision_capture_trigger()
    await manager.wait_for_idle()

    # Then: exactly one frame arrives with the original behavior intact.
    assert len(listener.received) == 1
    frame_data = listener.received[0]
    assert isinstance(frame_data, VisionFrameData)
    assert frame_data.dept == "fun"
    assert isinstance(frame_data.frame, bytes)
    assert len(frame_data.frame) > 0

    await manager.disable_plugin(plugin.name)
    await manager.disable_plugin(listener.name)


def test_static_vision_capture_fallback():
    plugin = StaticVisionPlugin(config_dir=None)
    with patch.dict("os.environ", {"XDG_SESSION_TYPE": "unknown"}, clear=True):
        frame = plugin.capture_frame()
        assert isinstance(frame, bytes)
        assert len(frame) > 0
