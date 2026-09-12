"""Todo-3 lifecycle tests: internal capture task replacing self-scheduled INTERVAL.

Todo 9 extends this file later with periodic-describe tests — keep every test
here additive and prefixed ``test_capture_``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from kateto.core.event import (
    PluginErrorData,
    ScheduleRequestData,
    ScheduleResultData,
    ScheduleType,
    VisionFrameData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.plugins.executor.scheduler import SchedulerPlugin
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


# --- Todo-9 periodic-describe tests (additive; every name prefixed test_periodic_) ---


class _Voice(Plugin):
    """Minimal voice stand-in (capability-gated scheduling target)."""

    def __init__(self, name: str = "jane") -> None:
        super().__init__(name=name, capabilities=("voice",))


class _ScheduleResultRecorder(Plugin):
    """Records every schedule_result seen on the bus."""

    def __init__(self) -> None:
        super().__init__(name="schedule_result_recorder")
        self.seen: list[ScheduleResultData] = []

    async def on_schedule_result(self, data: ScheduleResultData) -> None:
        self.seen.append(data)


def _noise_payload(seed: int) -> bytes:
    import io
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


async def _make_quiet_plugin(manager: PluginManager, **kwargs) -> StaticVisionPlugin:
    """Enabled vision plugin with a neutered capture loop (deterministic buffers)."""
    plugin = StaticVisionPlugin(capture_fps=20.0, config_dir=None, **kwargs)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    plugin._windows.clear()
    plugin._dropped.clear()
    return plugin


@pytest.mark.asyncio
async def test_periodic_one_job_per_opted_in_voice():
    # Given: scheduler + recorders + one voice, vision opted in for it
    manager = PluginManager()
    scheduler = SchedulerPlugin()
    await manager.enable_plugin(scheduler)
    requests = _ScheduleRequestRecorder()
    await manager.enable_plugin(requests)
    results = _ScheduleResultRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(_Voice("jane"))
    plugin = StaticVisionPlugin(opted_in=(("jane", "30s"),), capture_fps=20.0)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]

    # When: vision enables
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Then: exactly ONE stable INTERVAL job for jane, no error
    vision_requests = [r for r in requests.seen if r.event_name == "vision_describe_request"]
    assert len(vision_requests) == 1
    request = vision_requests[0]
    assert request.job_id == "vision-describe-jane"
    assert request.schedule_type is ScheduleType.INTERVAL
    assert request.expression == "30s"
    assert request.target_voice == "jane"
    assert request.data == {"requester": "scheduler:jane"}
    assert plugin._periodic_jobs == ["vision-describe-jane"]
    assert "vision-describe-jane" in scheduler._jobs
    job_results = [r for r in results.seen if r.job_id == "vision-describe-jane"]
    assert len(job_results) == 1 and job_results[0].error is None

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(scheduler.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_reenable_no_duplicate_and_disable_cancels():
    # Given: the one-job setup above, through two enable/disable cycles
    manager = PluginManager()
    scheduler = SchedulerPlugin()
    await manager.enable_plugin(scheduler)
    results = _ScheduleResultRecorder()
    await manager.enable_plugin(results)
    await manager.enable_plugin(_Voice("jane"))
    plugin = StaticVisionPlugin(opted_in=(("jane", "30s"),), capture_fps=20.0)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # When: disabled → zero further fires, jobs cleared on both sides
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await manager.wait_for_idle()
    assert plugin._periodic_jobs == []
    assert "vision-describe-jane" not in scheduler._jobs

    # When: re-enabled → no "already scheduled" error, exactly one job again
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()
    assert plugin._periodic_jobs == ["vision-describe-jane"]
    assert "vision-describe-jane" in scheduler._jobs

    # Then: no result ever carried an error for our job
    job_results = [r for r in results.seen if r.job_id == "vision-describe-jane"]
    assert job_results and all(r.error is None for r in job_results)

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(scheduler.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_unknown_voice_skipped_with_reason():
    # Given: a manager whose only voice is jane, vision opted in for a ghost
    manager = PluginManager()
    requests = _ScheduleRequestRecorder()
    await manager.enable_plugin(requests)
    await manager.enable_plugin(_Voice("jane"))
    plugin = StaticVisionPlugin(opted_in=(("ghost", "30s"),), capture_fps=20.0)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]

    # When: vision enables
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Then: skipped with reason, no job, no crash
    assert [r for r in requests.seen if r.event_name == "vision_describe_request"] == []
    assert plugin._periodic_jobs == []
    assert "ghost" in plugin._periodic_skipped
    assert "ghost" in plugin._periodic_skipped["ghost"]

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_non_opted_in_voice_gets_no_job():
    # Given: two voices, opt-in for only one
    manager = PluginManager()
    requests = _ScheduleRequestRecorder()
    await manager.enable_plugin(requests)
    await manager.enable_plugin(_Voice("jane"))
    await manager.enable_plugin(_Voice("doktor"))
    plugin = StaticVisionPlugin(opted_in=(("jane", "30s"),), capture_fps=20.0)
    plugin.capture_frame = lambda target_pid=None: b""  # type: ignore[method-assign]

    # When: vision enables
    await manager.enable_plugin(plugin)
    await manager.wait_for_idle()

    # Then: exactly one job (jane), doktor untouched
    vision_requests = [r for r in requests.seen if r.event_name == "vision_describe_request"]
    assert [r.target_voice for r in vision_requests] == ["jane"]

    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_talking_state_defers_tick():
    # Given: scheduler + vision (contracts registered), one voice, no opt-in noise
    manager = PluginManager()
    scheduler = SchedulerPlugin()
    await manager.enable_plugin(scheduler)
    await manager.enable_plugin(_Voice("jane"))
    plugin = await _make_quiet_plugin(manager)
    envelopes: list[Any] = []
    manager.add_event_observer(envelopes.append)
    job_id = await scheduler._schedule(
        ScheduleRequestData(
            schedule_type=ScheduleType.INTERVAL,
            expression="30s",
            event_name="vision_describe_request",
            data={"requester": "scheduler:jane"},
            job_id="vision-describe-jane",
            target_voice="jane",
        )
    )
    job = scheduler._jobs[job_id]

    # When: the voice is talking → tick deferred per scheduler.py:221-223, no crash
    scheduler._voice_status["jane"] = "talking"
    await scheduler._fire(job, datetime.now().astimezone())
    assert job_id in scheduler._jobs
    assert [e for e in envelopes if e.name == "vision_describe_request"] == []

    # When: the voice goes idle → next fire dispatches
    scheduler._voice_status["jane"] = "idle"
    await scheduler._fire(job, datetime.now().astimezone())
    fired = [e for e in envelopes if e.name == "vision_describe_request"]
    assert len(fired) == 1
    assert fired[0].target == "jane"

    manager.remove_event_observer(envelopes.append)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
    await asyncio.wait_for(manager.disable_plugin(scheduler.name), timeout=5.0)


@pytest.mark.asyncio
async def test_periodic_scheduler_request_emits_targeted_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a frame in the window and a canned primary client
    from kateto.plugins.executor import static_vision_plugin as svp

    def fake_openai_client(endpoint, api_key, retries, timeout):
        async def create(**kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="a cat on a desk"))]
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(svp, "_openai_client", fake_openai_client)
    manager = PluginManager()
    plugin = await _make_quiet_plugin(manager)
    plugin._append_frame("screen", _noise_payload(101), 100.0)
    plugin._append_frame("screen", _noise_payload(102), 101.0)
    envelopes: list[Any] = []
    manager.add_event_observer(envelopes.append)

    # When: a scheduler-originated request arrives
    from kateto.core.event import VisionDescribeRequestData

    await plugin.on_vision_describe_request(
        VisionDescribeRequestData(requester="scheduler:jane", source="screen")
    )
    await manager.wait_for_idle()

    # Then: the ambient narration goes out with ENVELOPE target (not a data field)
    generates = [e for e in envelopes if e.name == "generate"]
    assert len(generates) == 1
    assert generates[0].target == "jane"
    assert generates[0].data.prompt.startswith("[look-at screen 1s]:")

    manager.remove_event_observer(envelopes.append)
    await asyncio.wait_for(manager.disable_plugin(plugin.name), timeout=5.0)
