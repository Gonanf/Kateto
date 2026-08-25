from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, override

from croniter import croniter
from pydantic import ConfigDict, Field, JsonValue

from kateto.core.event import (
    EventModel,
    ScheduleCancelData,
    ScheduleRequestData,
    ScheduleResultData,
    ScheduleType,
    VoiceStatusData,
)
from kateto.core.plugin import Plugin

if TYPE_CHECKING:
    from kateto.core.manager import PluginManager


class _GenericPayload(EventModel):
    """Fallback envelope body for scheduled events without a registered contract."""

    model_config = ConfigDict(extra="allow", frozen=False, strict=False)

    values: dict[str, JsonValue] = Field(default_factory=dict)


_DURATION_RE = re.compile(r"^(\d+)(s|m|h)$")


class ScheduleError(ValueError):
    pass


def _parse_duration(expression: str) -> timedelta:
    match = _DURATION_RE.match(expression.strip().lower())
    if match is None:
        msg = f"invalid duration expression: {expression!r} (use e.g. 30s, 5m, 1h)"
        raise ScheduleError(msg)
    value = int(match.group(1))
    unit = match.group(2)
    seconds = {"s": value, "m": value * 60, "h": value * 3600}[unit]
    return timedelta(seconds=seconds)


@dataclass(slots=True)
class _Job:
    job_id: str
    schedule_type: ScheduleType
    event_name: str
    data: dict[str, object]
    target_voice: str | None
    dept: str | None
    next_run: datetime
    jitter_seconds: float
    max_fires: int | None
    active_hours: tuple[int, int] | None
    interval: timedelta | None = None
    cron: croniter | None = None
    fires: int = 0
    paused: bool = field(default=False)

    def compute_next(self, base: datetime) -> datetime:
        if self.schedule_type is ScheduleType.INTERVAL:
            return base + self.interval  # type: ignore[operator]
        if self.schedule_type is ScheduleType.CRON:
            assert self.cron is not None
            return self.cron.get_next(datetime, start_time=base)
        return base


def _parse_active_hours(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    try:
        start_s, end_s = value.split("-", maxsplit=1)
        start = int(start_s.strip().split(":")[0])
        end = int(end_s.strip().split(":")[0])
    except (ValueError, AttributeError) as error:
        msg = f"invalid active_hours: {value!r} (use e.g. 09:00-22:00)"
        raise ScheduleError(msg) from error
    if not (0 <= start <= 23 and 0 <= end <= 23):
        msg = f"invalid active_hours: {value!r}"
        raise ScheduleError(msg)
    return start, end


class SchedulerPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("executor_scheduler", receive_self_events=True)
        self._jobs: dict[str, _Job] = {}
        self._voice_status: dict[str, str] = {}
        self._ticker: asyncio.Task[None] | None = None
        self._wake: asyncio.Event = asyncio.Event()

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("schedule_request", ScheduleRequestData)
        manager.register_event("schedule_result", ScheduleResultData)
        manager.register_event("schedule_cancel", ScheduleCancelData)
        manager.register_event("voice_status", VoiceStatusData)

    @override
    async def enable(self) -> None:
        self._ticker = asyncio.create_task(self._tick(), name="kateto-scheduler")

    @override
    async def disable(self) -> None:
        if self._ticker is not None:
            self._ticker.cancel()
            try:
                await self._ticker
            except asyncio.CancelledError:
                pass
            self._ticker = None
        self._jobs.clear()
        self._voice_status.clear()

    async def on_voice_status(self, data: VoiceStatusData) -> None:
        self._voice_status[data.voice] = data.status.value

    async def on_schedule_request(self, data: ScheduleRequestData) -> None:
        manager = self.required_manager
        try:
            job_id = await self._schedule(data)
        except ScheduleError as error:
            await manager.emit(
                "schedule_result",
                ScheduleResultData(job_id=data.job_id or "", error=str(error)),
                source=self.name,
            )
            return
        job = self._jobs[job_id]
        await manager.emit(
            "schedule_result",
            ScheduleResultData(job_id=job_id, next_run=job.next_run.isoformat()),
            source=self.name,
        )

    async def on_schedule_cancel(self, data: ScheduleCancelData) -> None:
        manager = self.required_manager
        job = self._jobs.pop(data.job_id, None)
        await manager.emit(
            "schedule_result",
            ScheduleResultData(job_id=data.job_id, next_run=None, error=None if job else "job not found"),
            source=self.name,
        )

    async def _schedule(self, data: ScheduleRequestData) -> str:
        job_id = data.job_id or uuid.uuid4().hex[:12]
        if job_id in self._jobs:
            msg = f"job already scheduled: {job_id}"
            raise ScheduleError(msg)
        now = datetime.now().astimezone()
        interval = None
        cron = None
        if data.schedule_type in (ScheduleType.ONE_SHOT, ScheduleType.INTERVAL):
            interval = _parse_duration(data.expression)
        else:
            try:
                cron = croniter(data.expression, now)
            except (ValueError, KeyError) as error:
                msg = f"invalid cron expression: {data.expression!r}"
                raise ScheduleError(msg) from error
        job = _Job(
            job_id=job_id,
            schedule_type=data.schedule_type,
            event_name=data.event_name,
            data=data.data,
            target_voice=data.target_voice,
            dept=data.dept,
            next_run=now,
            jitter_seconds=data.jitter_seconds,
            max_fires=data.max_fires,
            active_hours=_parse_active_hours(data.active_hours),
            interval=interval,
            cron=cron,
        )
        job.next_run = self._first_run(job, now)
        self._jobs[job_id] = job
        self._wake.set()
        return job_id

    def _first_run(self, job: _Job, base: datetime) -> datetime:
        if job.schedule_type is ScheduleType.ONE_SHOT:
            return base + job.interval  # type: ignore[operator]
        return job.compute_next(base)

    async def _tick(self) -> None:
        while True:
            self._wake.clear()
            now = datetime.now().astimezone()
            due = [job for job in self._jobs.values() if job.next_run <= now]
            for job in due:
                await self._fire(job, now)
            if not self._jobs:
                await self._wake.wait()
                continue
            soonest = min(job.next_run for job in self._jobs.values())
            wait = max((soonest - datetime.now().astimezone()).total_seconds(), 0)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=min(wait, 3600))
            except TimeoutError:
                pass

    async def _fire(self, job: _Job, now: datetime) -> None:
        manager = self.required_manager
        if job.paused:
            return
        if job.active_hours is not None and not self._in_active_hours(job, now):
            job.next_run = job.compute_next(now)
            return
        if job.target_voice is not None and job.target_voice in self._voice_status and self._voice_status[job.target_voice] in {"talking", "thinking"}:
            job.next_run = job.compute_next(now)
            return
        target = job.target_voice
        if target is None:
            target = self._pick_random_voice()
        payload = dict(job.data)
        if job.jitter_seconds:
            import random

            payload["_delay_seconds"] = round(random.uniform(0, job.jitter_seconds), 3)
        # The bus only accepts Pydantic models: coerce the stored dict through
        # the registered contract (or a generic fallback) before emitting.
        contract = manager.get_event_contract(job.event_name)
        if contract is not None:
            data = contract.model_validate(payload)
        else:
            # ponytail: dict[str, object] → JsonValue is trusted because the
            # payload came from a JSON tool call; tighten when jobs persist.
            data = _GenericPayload(values=payload)  # type: ignore[arg-type]
        await manager.emit(job.event_name, data, source=self.name, target=target, dept=job.dept)
        job.fires += 1
        if job.max_fires is not None and job.fires >= job.max_fires:
            self._jobs.pop(job.job_id, None)
            return
        if job.schedule_type is ScheduleType.ONE_SHOT:
            self._jobs.pop(job.job_id, None)
            return
        job.next_run = job.compute_next(now)

    def _in_active_hours(self, job: _Job, now: datetime) -> bool:
        start, end = job.active_hours  # type: ignore[misc]
        hour = now.hour
        return start <= hour < end

    def _pick_random_voice(self) -> str | None:
        import random

        voices = [
            plugin.name
            for plugin in self.required_manager.get_plugins()
            if "voice" in plugin.capabilities and plugin.enabled
        ]
        return random.choice(voices) if voices else None
