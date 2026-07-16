#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from kateto.core import PluginManager, WorkflowEngine
from kateto.core.event import (
    VoiceIdleData,
    WorkflowCheckpointResult,
    WorkflowPhaseCompleteData,
    WorkflowRunData,
)
from kateto.core.workflow import (
    WorkflowCatalog,
    WorkflowDefinition,
    WorkflowDefinitionError,
    WorkflowNotFoundError,
    WorkflowPhaseStatus,
    WorkflowStatus,
)
from kateto.core.workflow_engine import WorkflowSnapshot


_LIFECYCLE_EVENTS = frozenset(
    {
        "workflow_started",
        "workflow_phase_start",
        "workflow_phase_complete",
        "workflow_completed",
    },
)


class WorkflowFixtureError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class WorkflowFixtureResult:
    lifecycle: tuple[str, ...]
    deliverable: str
    failed_checkpoint: str
    no_next_phase: bool
    passed: bool


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "defaults"


def _expected_lifecycle(phase_count: int) -> tuple[str, ...]:
    names = ["workflow_started", "workflow_phase_start"]
    for phase_index in range(phase_count):
        names.append("workflow_phase_complete")
        if phase_index + 1 < phase_count:
            names.append("workflow_phase_start")
    names.append("workflow_completed")
    return tuple(names)


def _lifecycle_names(manager: PluginManager) -> tuple[str, ...]:
    return tuple(event.name for event in manager.get_events() if event.name in _LIFECYCLE_EVENTS)


async def _complete_successfully(
    manager: PluginManager,
    definition: WorkflowDefinition,
    voice: str,
) -> tuple[str, ...]:
    await manager.emit(
        "workflow_run",
        WorkflowRunData(workflow=definition.name, voice=voice),
        source="workflow_fixture",
    )
    await manager.wait_for_idle()
    for phase in definition.phases:
        checkpoints = [
            WorkflowCheckpointResult(checkpoint=checkpoint, passed=True)
            for checkpoint in phase.checkpoints
        ]
        await manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow=definition.name,
                phase_id=phase.id,
                voice=voice,
                deliverables=list(phase.deliverables),
                checkpoint_results=checkpoints,
            ),
            source=voice.casefold(),
        )
        await manager.wait_for_idle()
        await manager.emit("voice_idle", VoiceIdleData(voice=voice), source=voice.casefold())
        await manager.wait_for_idle()
    return _lifecycle_names(manager)


async def run_fixture(workflow: str, voice: str, config_dir: Path) -> WorkflowFixtureResult:
    definition = WorkflowCatalog(config_dir=config_dir).load(workflow=workflow, voice=voice)
    first_phase = definition.phases[0]
    if not first_phase.checkpoints:
        raise WorkflowFixtureError("fixture needs a first-phase checkpoint")
    if not definition.phases[-1].deliverables:
        raise WorkflowFixtureError("fixture needs a final-phase deliverable")
    deliverable = definition.phases[-1].deliverables[-1]

    success_manager = PluginManager()
    success_engine = WorkflowEngine(config_dir=config_dir)
    await success_manager.enable_plugin(success_engine)
    try:
        lifecycle = await _complete_successfully(success_manager, definition, voice)
        success_snapshot = success_engine.snapshot(workflow=workflow, voice=voice)
    finally:
        await success_manager.close()

    failure_manager = PluginManager()
    failure_engine = WorkflowEngine(config_dir=config_dir)
    await failure_manager.enable_plugin(failure_engine)
    try:
        failed_checkpoint = first_phase.checkpoints[0]
        await failure_manager.emit(
            "workflow_run",
            WorkflowRunData(workflow=workflow, voice=voice),
            source="workflow_fixture",
        )
        await failure_manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow=workflow,
                phase_id=first_phase.id,
                voice=voice,
                checkpoint_results=[WorkflowCheckpointResult(checkpoint=failed_checkpoint, passed=False)],
            ),
            source=voice.casefold(),
        )
        await failure_manager.emit("voice_idle", VoiceIdleData(voice=voice), source=voice.casefold())
        await failure_manager.wait_for_idle()
        failure_snapshot = failure_engine.snapshot(workflow=workflow, voice=voice)
        failure_names = _lifecycle_names(failure_manager)
    finally:
        await failure_manager.close()

    match success_snapshot:
        case WorkflowSnapshot(status=WorkflowStatus.COMPLETED, phase_status=WorkflowPhaseStatus.DONE):
            success_completed = True
        case _:
            success_completed = False
    match failure_snapshot:
        case WorkflowSnapshot(status=WorkflowStatus.PAUSED, phase_status=WorkflowPhaseStatus.IN_PROGRESS):
            checkpoint_paused = True
        case _:
            checkpoint_paused = False
    no_next_phase = failure_names.count("workflow_phase_start") == 1
    passed = (
        lifecycle == _expected_lifecycle(len(definition.phases))
        and success_completed
        and checkpoint_paused
        and no_next_phase
        and "workflow_checkpoint_fail" in tuple(event.name for event in failure_manager.get_events())
    )
    return WorkflowFixtureResult(
        lifecycle=lifecycle,
        deliverable=deliverable,
        failed_checkpoint=first_phase.checkpoints[0],
        no_next_phase=no_next_phase,
        passed=passed,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--voice", required=True)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(run_fixture(arguments.workflow, arguments.voice, _config_dir()))
    except (WorkflowDefinitionError, WorkflowFixtureError, WorkflowNotFoundError) as error:
        print(f"RESULT status=FAIL error={error}")
        print("CLEANUP managers_closed=true")
        return 2
    print(f"ORDERED_LIFECYCLE {' > '.join(result.lifecycle)}")
    print(f"DELIVERABLE path={result.deliverable}")
    print(f"CHECKPOINT_FAILURE checkpoint={result.failed_checkpoint}")
    print(f"NO_NEXT_PHASE={str(result.no_next_phase).lower()}")
    print(f"RESULT status={'PASS' if result.passed else 'FAIL'}")
    print("CLEANUP managers_closed=true")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
