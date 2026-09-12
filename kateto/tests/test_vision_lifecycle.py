"""Todo-3 lifecycle tests: internal capture task replacing self-scheduled INTERVAL.

Todo 9 extends this file later with periodic-describe tests — keep every test
here additive and prefixed ``test_capture_``.
"""

from __future__ import annotations

import asyncio

import pytest

from kateto.core.event import PluginErrorData, ScheduleRequestData, VisionFrameData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor.static_vision_plugin import StaticVisionPlugin


class _ScheduleRequestRecorder(Plugin):
    """Records every schedule_request seen on the bus."""

    def __init__(self) -> None:
        super().__init__(name="schedule_recorder")
        self.seen: list[ScheduleRequestData] = []

    async def on_schedule_request(self, data: ScheduleRequestData) -> None:
        self.seen.append(data)


class _ErrorRecorder(Plugin):
    """Records every error event seen on the bus."""

    def __init__(self) -> None:
        super().__init__(name="error_recorder")
        self.seen: list[PluginErrorData] = []

    async def on_error(self, data: PluginErrorData) -> None:
        self.seen.append(data)


class _FrameRecorder(Plugin):
    """Records every vision_frame seen on the bus."""

    def __init__(self) -> None:
        super().__init__(name="frame_recorder")
        self.seen: list[VisionFrameData] = []

    async def on_vision_frame(self, data: VisionFrameData) -> None:
        self.seen.append(data)


async def _wait_for(predicate, timeout: float = 5.0):
    """Poll predicate until truthy; raise TimeoutError on expiry."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if predicate():
            return
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_capture_task_fills_buffer_and_stops():
    # Given: a vision plugin with a fast capture rate (headless → dummy PNG)
    manager = PluginManager()
    plugin = StaticVisionPlugin(dept="fun", capture_fps=20.0)
    await manager.enable_plugin(plugin)

    # When: enabled and idle
    await _wait_for(lambda: len(plugin._windows.get("screen", ())) > 0)
    # Then: exactly one capture task is alive
    assert plugin._capture_task is not None and not plugin._capture_task.done()

    # When: disabled (cancel awaited with a timeout = hung-command guard)
    size_at_disable = len(plugin._windows["screen"])
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    # Then: task is done and the buffer stops growing
    assert plugin._capture_task is None or plugin._capture_task.done()
    await asyncio.sleep(0.2)
    assert len(plugin._windows["screen"]) == size_at_disable


@pytest.mark.asyncio
async def test_capture_trigger_appends_and_emits():
    # Given: an enabled plugin with recorders
    manager = PluginManager()
    plugin = StaticVisionPlugin(dept="fun", capture_fps=0.5)
    frames = _FrameRecorder()
    await manager.enable_plugin(frames)
    await manager.enable_plugin(plugin)
    before = len(plugin._windows.get("screen", ()))

    # When: the compat trigger fires
    await plugin.on_vision_capture_trigger()
    await manager.wait_for_idle()

    # Then: the frame lands in the buffer AND on the bus
    assert len(plugin._windows.get("screen", ())) == before + 1
    assert len(frames.seen) == 1
    assert frames.seen[0].dept == "fun"

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await manager.disable_plugin(frames.name)


@pytest.mark.asyncio
async def test_capture_plugin_emits_no_schedule_request():
    # Given: an enabled plugin with a schedule_request recorder
    manager = PluginManager()
    recorder = _ScheduleRequestRecorder()
    await manager.enable_plugin(recorder)
    plugin = StaticVisionPlugin(dept="fun", capture_fps=20.0)
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # When/Then: the plugin itself schedules no jobs
    assert [r for r in recorder.seen] == []
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await manager.disable_plugin(recorder.name)


@pytest.mark.asyncio
async def test_capture_error_keeps_loop_alive():
    # Given: capture_frame fails twice, then recovers (headless dummy path)
    manager = PluginManager()
    errors = _ErrorRecorder()
    await manager.enable_plugin(errors)
    plugin = StaticVisionPlugin(dept="fun", capture_fps=20.0)
    real_capture = plugin.capture_frame
    calls = {"n": 0}

    def flaky(target_pid=None):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        return real_capture(target_pid)

    plugin.capture_frame = flaky  # type: ignore[method-assign]
    await manager.enable_plugin(plugin)

    # When: the loop survives the failures
    await _wait_for(lambda: len(errors.seen) >= 1)
    await _wait_for(lambda: len(plugin._windows.get("screen", ())) > 0)

    # Then: errors surfaced on the bus, bus stayed up, task keeps looping
    assert errors.seen[0].plugin == "static_vision"
    assert plugin._capture_task is not None and not plugin._capture_task.done()
    size = len(plugin._windows["screen"])
    await _wait_for(lambda: len(plugin._windows["screen"]) > size)
    await manager.wait_for_idle()  # bus still dispatches

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await manager.disable_plugin(errors.name)


@pytest.mark.asyncio
async def test_capture_double_enable_disable_safe():
    # Given: an enabled plugin
    manager = PluginManager()
    plugin = StaticVisionPlugin(dept="fun", capture_fps=20.0)
    await manager.enable_plugin(plugin)
    await _wait_for(lambda: len(plugin._windows.get("screen", ())) > 0)
    first_task = plugin._capture_task

    # When: enabled again (direct re-enable is a no-op, no second task)
    await plugin.enable()
    # Then: still exactly one live task
    assert plugin._capture_task is first_task
    assert not plugin._capture_task.done()

    # When: disabled twice via the manager (second is a safe no-op)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    assert plugin._capture_task is None or plugin._capture_task.done()

    # When: re-enabled after disable
    await manager.enable_plugin(plugin)
    # Then: a fresh task runs and the buffer grows again (no already-scheduled error)
    assert plugin._capture_task is not None and not plugin._capture_task.done()
    assert plugin._capture_task is not first_task
    await _wait_for(lambda: len(plugin._windows.get("screen", ())) > 0)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
