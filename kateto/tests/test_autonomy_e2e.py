"""Autonomy e2e: voices acting without a human present.

Covers the no-person mode end to end on the real bus:
- schedule_event tool → SchedulerPlugin fires the event later
- fired event lands as a real generate on the target voice
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.event import (
    GenerateData,
    GenerateRequestData,
    ScheduleRequestData,
    ScheduleResultData,
    ScheduleType,
    VoiceRequestData,
)
from kateto.plugins.executor.scheduler import SchedulerPlugin
from kateto.voices.tools import VoiceToolExecutor


class _Recorder(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.events: list[tuple[str, object]] = []

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("generate", GenerateData)
        manager.register_event("generate_request", GenerateRequestData)
        manager.register_event("voice_request", VoiceRequestData)

    async def on_generate(self, data: GenerateData) -> None:
        self.events.append(("generate", data))

    async def on_generate_request(self, data: GenerateRequestData) -> None:
        self.events.append(("generate_request", data))

    async def on_voice_request(self, data: VoiceRequestData) -> None:
        self.events.append(("voice_request", data))


async def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_scheduled_job_fires_and_reaches_target_voice(tmp_path: Path) -> None:
    # Given: the scheduler is enabled and a voice tool executor bound to it.
    manager = PluginManager()
    await manager.enable_plugin(SchedulerPlugin())
    recorder = _Recorder("jane")
    await manager.enable_plugin(recorder)

    executor = VoiceToolExecutor(config_dir=tmp_path, manager=manager, voice_name="doktor")

    # When: a voice schedules a one-shot event 1s out targeting jane.
    raw = await executor.execute(
        "schedule_event",
        {
            "event_name": "generate",
            "delay": 1,
            "target_voice": "jane",
            "data": {"prompt": "standup in five minutes"},
            "job_id": "autonomy-e2e-1",
        },
    )
    result = json.loads(raw)

    # Then: the scheduling round-trip confirms the job.
    assert result["status"] == "scheduled"
    assert result["job_id"] == "autonomy-e2e-1"
    await manager.wait_for_idle(timeout=5)
    results = [
        event.data
        for event in manager.get_events()
        if isinstance(event.data, ScheduleResultData)
    ]
    assert any(r.job_id == "autonomy-e2e-1" and r.error is None for r in results)

    # When: the scheduled moment passes.
    fired = await _wait_until(lambda: bool(recorder.events))

    # Then: the scheduler fired the real event onto the bus, targeted at jane.
    assert fired, f"scheduled job never fired; events={recorder.events}"
    generates = [data for name, data in recorder.events if name == "generate"]
    assert len(generates) == 1
    assert generates[0].prompt == "standup in five minutes"


@pytest.mark.asyncio
async def test_scheduler_reports_error_for_bad_cron(tmp_path: Path) -> None:
    # Given: an enabled scheduler.
    manager = PluginManager()
    await manager.enable_plugin(SchedulerPlugin())
    executor = VoiceToolExecutor(config_dir=tmp_path, manager=manager, voice_name="jane")

    # When: a voice schedules with a malformed cron expression.
    raw = await executor.execute(
        "schedule_event",
        {"event_name": "generate", "cron": "not-a-cron", "data": {}},
    )
    await manager.wait_for_idle(timeout=5)

    # Then: the error surfaces through schedule_result instead of vanishing.
    results = [
        event.data
        for event in manager.get_events()
        if isinstance(event.data, ScheduleResultData)
    ]
    assert results and all(r.error for r in results)


@pytest.mark.asyncio
async def test_schedule_request_contract_round_trips_without_scheduler(tmp_path: Path) -> None:
    # Given: no scheduler plugin (it can be disabled via [plugin.executor_scheduler]).
    manager = PluginManager()
    request = ScheduleRequestData(
        schedule_type=ScheduleType.ONE_SHOT,
        expression="5s",
        event_name="generate",
        data={"prompt": "hi"},
        job_id="contract-check",
    )
    manager.register_event("schedule_request", ScheduleRequestData)

    # When/Then: emitting the contract is valid even with no receiver (bus stays up).
    envelope = await manager.emit("schedule_request", request, source="test")
    assert envelope.name == "schedule_request"
