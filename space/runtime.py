from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from threading import Lock
from typing import Final, TypeAlias, final, override

import anyio
from anyio.from_thread import BlockingPortal, start_blocking_portal
from pydantic import BaseModel, JsonValue

from kateto.core.event import (
    EventModel,
    EventEnvelope,
    GenerateData,
    TextChunk,
    TodoItemData,
    VoiceStatus,
    VoiceStatusData,
    WorkflowCompletedData,
    WorkflowPhaseCompleteData,
    WorkflowPhaseStartData,
    WorkflowStartedData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin

from space.contracts import ProviderSelection

JsonRecord: TypeAlias = dict[str, JsonValue]
RuntimeBuilder: TypeAlias = Callable[[ProviderSelection], tuple[PluginManager, tuple[Plugin, ...]]]
_FIXTURE_WORKFLOW: Final[str] = "space-plan"


class SpacePlanData(EventModel):
    prompt: str
    provider: str
    voice: str


class SpaceArtifactData(EventModel):
    name: str
    kind: str
    content: str


@final
@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    provider: str
    mode: str
    closed: bool
    events: tuple[JsonRecord, ...]
    notifications: tuple[JsonRecord, ...]
    plans: tuple[JsonRecord, ...]
    agent_statuses: tuple[JsonRecord, ...]
    workflows: tuple[JsonRecord, ...]
    mcp: tuple[JsonRecord, ...]
    plugins: tuple[JsonRecord, ...]
    artifacts: tuple[JsonRecord, ...]

    def as_outputs(self) -> JsonRecord:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "closed": self.closed,
            "events": list(self.events),
            "notifications": list(self.notifications),
            "plans": list(self.plans),
            "agent_statuses": list(self.agent_statuses),
            "workflows": list(self.workflows),
            "mcp": list(self.mcp),
            "plugins": list(self.plugins),
            "artifacts": list(self.artifacts),
        }


@final
class _FixtureRuntimePlugin(Plugin):
    _selection: ProviderSelection

    def __init__(self, selection: ProviderSelection) -> None:
        super().__init__("space_fixture_runtime")
        self._selection = selection

    @override
    async def initialize(self) -> None:
        manager = self.manager
        if manager is None:
            raise RuntimeError("Space fixture runtime requires a manager")
        manager.register_event("space_plan", SpacePlanData)
        manager.register_event("space_artifact", SpaceArtifactData)
        manager.register_event("voice_status", VoiceStatusData)
        manager.register_event("workflow_started", WorkflowStartedData)
        manager.register_event("workflow_phase_start", WorkflowPhaseStartData)
        manager.register_event("workflow_phase_complete", WorkflowPhaseCompleteData)
        manager.register_event("workflow_completed", WorkflowCompletedData)
        manager.register_event("todo_updated", TodoItemData)

    async def on_generate(self, data: GenerateData) -> None:
        prompt = data.prompt
        if prompt is None:
            return
        if prompt == "provider-error":
            raise RuntimeError(f"{self._selection.provider} provider is unavailable")
        manager = self.manager
        if manager is None:
            raise RuntimeError("Space fixture runtime is not attached")
        _ = await manager.emit(
            "voice_status",
            VoiceStatusData(voice="doktor", status=VoiceStatus.THINKING),
            source=self.name,
        )
        _ = await manager.emit(
            "space_plan",
            SpacePlanData(prompt=prompt, provider=self._selection.provider, voice="doktor"),
            source=self.name,
        )
        _ = await manager.emit(
            "workflow_started",
            WorkflowStartedData(workflow=_FIXTURE_WORKFLOW, voice="doktor", context={"prompt": prompt}),
            source=self.name,
        )
        _ = await manager.emit(
            "workflow_phase_start",
            WorkflowPhaseStartData(
                workflow=_FIXTURE_WORKFLOW,
                phase_id="plan",
                voice="doktor",
                instructions=["Turn the request into an actionable plan"],
            ),
            source=self.name,
        )
        _ = await manager.emit(
            "todo_updated",
            TodoItemData(voice="doktor", task=prompt, completed=False),
            source=self.name,
        )
        _ = await manager.emit(
            "space_artifact",
            SpaceArtifactData(name="TODO.md", kind="todo", content=f"- [ ] {prompt}"),
            source=self.name,
        )
        _ = await manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow=_FIXTURE_WORKFLOW,
                phase_id="plan",
                voice="doktor",
                deliverables=["TODO.md"],
            ),
            source=self.name,
        )
        _ = await manager.emit(
            "workflow_completed",
            WorkflowCompletedData(workflow=_FIXTURE_WORKFLOW, voice="doktor"),
            source=self.name,
        )
        _ = await manager.emit(
            "text_chunk",
            TextChunk(text=f"Plan ready for: {prompt}", sequence=0, final=True, voice_id="doktor"),
            source=self.name,
        )
        _ = await manager.emit(
            "voice_status",
            VoiceStatusData(voice="doktor", status=VoiceStatus.IDLE),
            source=self.name,
        )


def _fixture_builder(selection: ProviderSelection) -> tuple[PluginManager, tuple[Plugin, ...]]:
    manager = PluginManager(event_limit=200)
    return manager, (_FixtureRuntimePlugin(selection),)


class SpaceRuntimeSession:
    def __init__(
        self,
        selection: ProviderSelection,
        manager: PluginManager,
        plugins: tuple[Plugin, ...],
    ) -> None:
        self.provider: str = selection.provider
        self.mode: str = "fixture"
        self.manager: PluginManager = manager
        self._plugins: tuple[Plugin, ...] = plugins
        self._session_key: str | None = selection.session_key
        self._started: bool = False
        self._closed: bool = False
        self._prompt_lock: anyio.Lock | None = None
        self._portal_stack: ExitStack | None = None
        self._portal: BlockingPortal | None = None
        self._portal_lock: Lock = Lock()

    @property
    def has_session_credentials(self) -> bool:
        return self._session_key is not None

    async def prompt(self, value: str) -> RuntimeSnapshot:
        if self._closed:
            raise RuntimeError("Space runtime session is closed")
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        if self._prompt_lock is None:
            self._prompt_lock = anyio.Lock()
        async with self._prompt_lock:
            await self._start()
            _ = await self.manager.emit("generate", GenerateData(prompt=prompt), source="space")
            await self.manager.wait_for_idle()
            return self.snapshot()

    def prompt_sync(self, value: str) -> RuntimeSnapshot:
        return self._blocking_portal().call(self.prompt, value)

    async def close(self) -> None:
        if not self._closed:
            try:
                await self.manager.close()
            finally:
                self._session_key = None
                self._closed = True

    def close_sync(self) -> None:
        with self._portal_lock:
            portal = self._portal
            stack = self._portal_stack
            if portal is None or stack is None:
                with start_blocking_portal() as temporary_portal:
                    temporary_portal.call(self.close)
                return
            try:
                portal.call(self.close)
            finally:
                stack.close()
                self._portal = None
                self._portal_stack = None

    def snapshot(self) -> RuntimeSnapshot:
        events = tuple(_event_record(event) for event in self.manager.get_events())
        notifications = tuple(
            _payload_record(record, kind="error")
            for record in events
            if record.get("name") == "error"
        )
        plans = tuple(
            _payload_record(record)
            for record in events
            if record.get("name") == "space_plan"
        )
        agent_statuses = _latest_by(events, "voice_status", "voice")
        workflows = tuple(
            _payload_record(record)
            for record in events
            if record.get("name") in {
                "workflow_started",
                "workflow_phase_start",
                "workflow_phase_complete",
                "workflow_completed",
            }
        )
        artifacts = tuple(
            _payload_record(record)
            for record in events
            if record.get("name") == "space_artifact"
        )
        plugins: tuple[JsonRecord, ...] = tuple(
            {
                "name": plugin.name,
                "enabled": plugin.enabled,
                "capabilities": list(plugin.capabilities),
            }
            for plugin in self.manager.get_plugins()
        )
        mcp: tuple[JsonRecord, ...] = (
            {"name": "mcp", "status": "fixture", "servers": []},
        )
        return RuntimeSnapshot(
            provider=self.provider,
            mode=self.mode,
            closed=self._closed,
            events=events,
            notifications=notifications,
            plans=plans,
            agent_statuses=agent_statuses,
            workflows=workflows,
            mcp=mcp,
            plugins=plugins,
            artifacts=artifacts,
        )

    async def _start(self) -> None:
        if self._started:
            return
        for plugin in self._plugins:
            await self.manager.enable_plugin(plugin)
        self._started = True

    def _blocking_portal(self) -> BlockingPortal:
        with self._portal_lock:
            if self._portal is None:
                stack = ExitStack()
                self._portal_stack = stack
                self._portal = stack.enter_context(start_blocking_portal())
            return self._portal


def create_runtime_session(
    selection: ProviderSelection,
    builder: RuntimeBuilder | None = None,
) -> SpaceRuntimeSession:
    selected_builder = _fixture_builder if builder is None else builder
    manager, plugins = selected_builder(selection)
    return SpaceRuntimeSession(selection, manager, plugins)


def _event_record(envelope: EventEnvelope[BaseModel]) -> JsonRecord:
    data: JsonValue = envelope.data.model_dump(mode="json")
    record: JsonRecord = {
        "name": envelope.name,
        "source": envelope.source,
        "timestamp": envelope.timestamp.isoformat(),
        "data": _redact(data),
    }
    return record


def _redact(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _latest_by(events: tuple[JsonRecord, ...], event_name: str, key: str) -> tuple[JsonRecord, ...]:
    latest: dict[str, JsonRecord] = {}
    for record in events:
        if record.get("name") != event_name:
            continue
        data = record.get("data")
        if isinstance(data, dict):
            value = data.get(key)
            if isinstance(value, str):
                latest[value] = record
    return tuple(latest.values())


def _payload_record(record: JsonRecord, *, kind: str | None = None) -> JsonRecord:
    payload = record.get("data")
    flattened: JsonRecord = {"name": record["name"]}
    if isinstance(payload, dict):
        flattened.update(payload)
    if kind is not None:
        flattened["kind"] = kind
    return flattened


async def close_runtime_session(session: SpaceRuntimeSession | None) -> None:
    if session is not None:
        await session.close()
