from unittest.mock import MagicMock, patch

import pytest

from kateto.core.event import ScheduleRequestData, VisionFrameData
from kateto.core.manager import PluginManager
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin


@pytest.mark.asyncio
async def test_static_vision_plugin_enable_and_trigger():
    manager = PluginManager()
    plugin = StaticVisionPlugin(interval_seconds=5.0, dept="fun")

    received_frames = []

    class VisionListener(PluginManager):
        pass

    async def frame_handler(data: VisionFrameData) -> None:
        received_frames.append(data)

    # Temporary listener plugin
    from kateto.core.plugin import Plugin

    class FrameListenerPlugin(Plugin):
        def __init__(self):
            super().__init__(name="frame_listener")

        async def on_vision_frame(self, data: VisionFrameData) -> None:
            received_frames.append(data)

    listener = FrameListenerPlugin()
    await manager.enable_plugin(listener)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Trigger static vision frame capture manually
    await plugin.on_vision_capture_trigger()
    await manager.wait_for_idle()

    assert len(received_frames) == 1
    frame_data = received_frames[0]
    assert isinstance(frame_data, VisionFrameData)
    assert frame_data.dept == "fun"
    assert isinstance(frame_data.frame, bytes)
    assert len(frame_data.frame) > 0

    await manager.disable_plugin(plugin.name)
    await manager.disable_plugin(listener.name)


def test_static_vision_capture_fallback():
    plugin = StaticVisionPlugin()
    with patch.dict("os.environ", {"XDG_SESSION_TYPE": "unknown"}, clear=True):
        frame = plugin.capture_frame()
        assert isinstance(frame, bytes)
        assert len(frame) > 0
