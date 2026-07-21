from __future__ import annotations

from typing import Final, Protocol, TypeAlias

from pydantic import JsonValue

JsonRecord: TypeAlias = dict[str, JsonValue]


class SnapshotView(Protocol):
    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def mode(self) -> str: ...

    @property
    def closed(self) -> bool: ...

    @property
    def events(self) -> tuple[JsonRecord, ...]: ...

    @property
    def notifications(self) -> tuple[JsonRecord, ...]: ...

    @property
    def plans(self) -> tuple[JsonRecord, ...]: ...

    @property
    def agent_statuses(self) -> tuple[JsonRecord, ...]: ...

    @property
    def workflows(self) -> tuple[JsonRecord, ...]: ...

    @property
    def mcp(self) -> tuple[JsonRecord, ...]: ...

    @property
    def plugins(self) -> tuple[JsonRecord, ...]: ...

    @property
    def artifacts(self) -> tuple[JsonRecord, ...]: ...


_AGENTS: Final[tuple[str, ...]] = ("jane", "doktor", "conquest")
_ACTION_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "space_plan",
        "workflow_started",
        "workflow_phase_start",
        "todo_updated",
        "space_artifact",
        "text_chunk",
    },
)


def snapshot_outputs(snapshot: SnapshotView) -> JsonRecord:
    return {
        "provider": snapshot.provider,
        "model": snapshot.model,
        "mode": snapshot.mode,
        "closed": snapshot.closed,
        "events": list(snapshot.events),
        "notifications": list(snapshot.notifications),
        "plans": list(snapshot.plans),
        "agent_statuses": list(snapshot.agent_statuses),
        "agents": _agents(snapshot),
        "workflows": _workflows(snapshot),
        "mcp": list(snapshot.mcp),
        "plugins": list(snapshot.plugins),
        "artifacts": list(snapshot.artifacts),
        "evolution": _evolution(snapshot),
    }


def _agents(snapshot: SnapshotView) -> list[JsonValue]:
    statuses = {
        record.get("voice"): record.get("status") for record in snapshot.agent_statuses
    }
    actions: dict[str, list[JsonValue]] = {agent: [] for agent in _AGENTS}
    for event in snapshot.events:
        name = event.get("name")
        if not isinstance(name, str) or name not in _ACTION_EVENTS:
            continue
        data = _data(event)
        voice = data.get("voice") or data.get("voice_id")
        if not isinstance(voice, str) or voice not in actions:
            continue
        action = _action(name, data)
        if action is not None:
            actions[voice].append(action)
    result: list[JsonValue] = []
    for agent in _AGENTS:
        result.append(
            {
                "name": agent.title(),
                "status": statuses.get(agent, "idle"),
                "actions": actions[agent],
            }
        )
    return result


def _workflows(snapshot: SnapshotView) -> list[JsonValue]:
    grouped: dict[str, JsonRecord] = {}
    phases: dict[str, list[JsonValue]] = {}
    tasks: dict[str, str] = {}
    for event in snapshot.events:
        name = event.get("name")
        data = _data(event)
        voice = data.get("voice")
        if (
            name == "todo_updated"
            and isinstance(voice, str)
            and isinstance(data.get("task"), str)
        ):
            tasks[voice] = str(data["task"])
        workflow = data.get("workflow")
        if not isinstance(workflow, str):
            continue
        entry = grouped.setdefault(
            workflow,
            {"workflow": workflow, "voice": data.get("voice", ""), "status": "running"},
        )
        phase_id = data.get("phase_id")
        if name == "workflow_phase_start" and isinstance(phase_id, str):
            entry["current_phase"] = phase_id
            phases.setdefault(workflow, []).append(
                {
                    "id": phase_id,
                    "status": "running",
                    "instructions": data.get("instructions", []),
                }
            )
        elif name == "workflow_phase_complete" and isinstance(phase_id, str):
            entry["current_phase"] = phase_id
            completed = _find_phase(phases.setdefault(workflow, []), phase_id)
            completed["status"] = "complete"
            completed["deliverables"] = data.get("deliverables", [])
            completed["checkpoints"] = data.get("checkpoint_results", [])
        elif name == "workflow_completed":
            entry["status"] = "complete"
    for workflow, entry in grouped.items():
        voice = entry.get("voice")
        entry["task"] = tasks.get(voice, "") if isinstance(voice, str) else ""
        entry["phases"] = phases.get(workflow, [])
        checkpoints: list[JsonValue] = []
        for phase in phases.get(workflow, []):
            for checkpoint in _records(
                phase.get("checkpoints") if isinstance(phase, dict) else []
            ):
                value = checkpoint.get("checkpoint")
                if checkpoint.get("passed") is True and isinstance(value, str):
                    checkpoints.append(value)
        entry["checkpoints_passed"] = checkpoints
    result: list[JsonValue] = []
    result.extend(grouped.values())
    return result


def _evolution(snapshot: SnapshotView) -> list[JsonValue]:
    entries: list[JsonValue] = []
    plan_indexes = [
        index
        for index, event in enumerate(snapshot.events)
        if event.get("name") == "space_plan"
    ]
    for offset, start in enumerate(plan_indexes):
        end = (
            plan_indexes[offset + 1]
            if offset + 1 < len(plan_indexes)
            else len(snapshot.events)
        )
        plan = _data(snapshot.events[start])
        events = snapshot.events[start:end]
        changes: list[JsonValue] = []
        for event in events:
            name = event.get("name")
            if isinstance(name, str):
                change = _action(name, _data(event))
                if change is not None:
                    changes.append(change)
        artifacts: list[JsonValue] = []
        for event in events:
            if event.get("name") == "space_artifact":
                artifact_name = _data(event).get("name")
                if artifact_name is not None:
                    artifacts.append(artifact_name)
        entries.append(
            {
                "prompt": plan.get("prompt", ""),
                "agent": str(plan.get("voice", "")),
                "workflow": _first_value(events, "workflow"),
                "changes": changes,
                "artifacts": artifacts,
            },
        )
    return entries


def _action(name: str, data: dict[str, JsonValue]) -> str | None:
    match name:
        case "space_plan":
            return "plan produced"
        case "workflow_started":
            return f"workflow started: {data.get('workflow', '')}"
        case "workflow_phase_start":
            return f"phase started: {data.get('phase_id', '')}"
        case "todo_updated":
            return f"task captured: {data.get('task', '')}"
        case "space_artifact":
            return f"artifact produced: {data.get('name', '')}"
        case "text_chunk":
            return "response delivered"
        case _:
            return None


def _data(record: JsonRecord) -> dict[str, JsonValue]:
    value = record.get("data")
    return value if isinstance(value, dict) else record


def _records(value: JsonValue) -> list[JsonRecord]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _find_phase(items: list[JsonValue], phase_id: str) -> JsonRecord:
    for item in items:
        if isinstance(item, dict) and item.get("id") == phase_id:
            return item
    phase: JsonRecord = {"id": phase_id, "status": "running"}
    items.append(phase)
    return phase


def _first_value(events: tuple[JsonRecord, ...], key: str) -> JsonValue:
    for event in events:
        value = _data(event).get(key)
        if value is not None:
            return value
    return ""
