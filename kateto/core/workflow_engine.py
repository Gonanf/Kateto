from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from pydantic import BaseModel

from kateto.core.event import (
    InterruptData,
    VoiceRequestData,
    VoiceIdleData,
    WorkflowCheckpointFailData,
    WorkflowCheckpointResult,
    WorkflowCompletedData,
    WorkflowPhaseCompleteData,
    WorkflowPhaseStartData,
    WorkflowRunData,
    WorkflowStartedData,
    WorkflowStopData,
)
from kateto.core.plugin import Plugin
from kateto.core.workflow import (
    WorkflowCatalog,
    WorkflowDefinition,
    WorkflowPhase,
    WorkflowPhaseStatus,
    WorkflowStatus,
)


@dataclass(frozen=True, slots=True)
class WorkflowSnapshot:
    workflow: str
    voice: str
    status: WorkflowStatus
    phase_id: str
    phase_status: WorkflowPhaseStatus


@dataclass(frozen=True, slots=True)
class _WorkflowKey:
    workflow: str
    voice: str


@dataclass(frozen=True, slots=True)
class _WorkflowRun:
    definition: WorkflowDefinition
    voice: str
    phase_index: int
    status: WorkflowStatus
    phase_status: WorkflowPhaseStatus


class WorkflowEngine(Plugin):
    def __init__(self, *, config_dir: Path) -> None:
        super().__init__("workflow_engine", capabilities=("workflow",))
        self._catalog = WorkflowCatalog(config_dir=config_dir)
        self._runs: dict[_WorkflowKey, _WorkflowRun] = {}

    @property
    def catalog(self) -> WorkflowCatalog:
        return self._catalog

    async def initialize(self) -> None:
        manager = self.manager
        if manager is None:
            return
        manager.register_event("workflow_run", WorkflowRunData)
        manager.register_event("workflow_started", WorkflowStartedData)
        manager.register_event("workflow_phase_start", WorkflowPhaseStartData)
        manager.register_event("workflow_phase_complete", WorkflowPhaseCompleteData)
        manager.register_event("workflow_checkpoint_fail", WorkflowCheckpointFailData)
        manager.register_event("workflow_completed", WorkflowCompletedData)
        manager.register_event("workflow_stop", WorkflowStopData)
        manager.register_event("workflow_stopped", WorkflowStopData)
        manager.register_event("voice_idle", VoiceIdleData)
        manager.register_event("voice_request", VoiceRequestData)
        manager.register_event("interrupt", InterruptData)

    async def on_workflow_run(self, data: WorkflowRunData) -> None:
        definition = self._catalog.load(workflow=data.workflow, voice=data.voice)
        key = self._key(data.workflow, data.voice)
        existing = self._runs.get(key)
        match existing:
            case _WorkflowRun(status=WorkflowStatus.RUNNING | WorkflowStatus.PAUSED):
                return
            case _:
                run = _WorkflowRun(
                    definition=definition,
                    voice=data.voice,
                    phase_index=0,
                    status=WorkflowStatus.RUNNING,
                    phase_status=WorkflowPhaseStatus.IN_PROGRESS,
                )
                self._runs[key] = run
        await self._emit(
            "workflow_started",
            WorkflowStartedData(workflow=definition.name, voice=data.voice, context=data.context),
        )
        await self._emit_phase_start(run)

    async def on_workflow_phase_complete(self, data: WorkflowPhaseCompleteData) -> None:
        key = self._key(data.workflow, data.voice)
        run = self._runs.get(key)
        match run:
            case _WorkflowRun(status=WorkflowStatus.RUNNING) as active:
                pass
            case _:
                return
        phase = active.definition.phases[active.phase_index]
        if phase.id.casefold() != data.phase_id.casefold():
            return
        match _failed_checkpoint(phase, data.checkpoint_results):
            case None:
                self._runs[key] = replace(active, phase_status=WorkflowPhaseStatus.DONE)
            case checkpoint:
                self._runs[key] = replace(active, status=WorkflowStatus.PAUSED)
                await self._emit(
                    "workflow_checkpoint_fail",
                    WorkflowCheckpointFailData(
                        workflow=active.definition.name,
                        phase_id=phase.id,
                        checkpoint=checkpoint,
                        voice=active.voice,
                    ),
                )

    async def on_voice_idle(self, data: VoiceIdleData) -> None:
        voice_key = data.voice.casefold()
        for key, run in tuple(self._runs.items()):
            match run:
                case _WorkflowRun(
                    definition=WorkflowDefinition(auto_advance=True),
                    status=WorkflowStatus.RUNNING,
                    phase_status=WorkflowPhaseStatus.DONE,
                ) if key.voice == voice_key:
                    await self._advance(key, run)
                case _:
                    continue

    async def on_workflow_stop(self, data: WorkflowStopData) -> None:
        key = self._key(data.workflow, data.voice)
        match self._runs.get(key):
            case _WorkflowRun(
                definition=WorkflowDefinition(can_stop=True),
                status=WorkflowStatus.RUNNING | WorkflowStatus.PAUSED,
            ) as active:
                self._runs[key] = replace(
                    active,
                    status=WorkflowStatus.STOPPED,
                    phase_status=WorkflowPhaseStatus.CANCELLED,
                )
                await self._emit("workflow_stopped", data)
            case _:
                return

    async def on_interrupt(self, data: InterruptData) -> None:
        for key, run in tuple(self._runs.items()):
            if run.status not in {WorkflowStatus.RUNNING, WorkflowStatus.PAUSED}:
                continue
            self._runs[key] = replace(
                run,
                status=WorkflowStatus.STOPPED,
                phase_status=WorkflowPhaseStatus.CANCELLED,
            )
            await self._emit(
                "workflow_stopped",
                WorkflowStopData(workflow=run.definition.name, voice=run.voice, reason=data.reason),
            )

    def snapshot(self, *, workflow: str, voice: str) -> WorkflowSnapshot | None:
        run = self._runs.get(self._key(workflow, voice))
        match run:
            case None:
                return None
            case active:
                phase = active.definition.phases[active.phase_index]
                return WorkflowSnapshot(
                    workflow=active.definition.name,
                    voice=active.voice,
                    status=active.status,
                    phase_id=phase.id,
                    phase_status=active.phase_status,
                )

    async def _advance(self, key: _WorkflowKey, run: _WorkflowRun) -> None:
        next_phase_index = run.phase_index + 1
        if next_phase_index == len(run.definition.phases):
            self._runs[key] = replace(run, status=WorkflowStatus.COMPLETED)
            await self._emit(
                "workflow_completed",
                WorkflowCompletedData(workflow=run.definition.name, voice=run.voice),
            )
            return
        next_run = replace(
            run,
            phase_index=next_phase_index,
            phase_status=WorkflowPhaseStatus.IN_PROGRESS,
        )
        self._runs[key] = next_run
        await self._emit_phase_start(next_run)

    async def _emit_phase_start(self, run: _WorkflowRun) -> None:
        phase = run.definition.phases[run.phase_index]
        await self._emit(
            "workflow_phase_start",
            WorkflowPhaseStartData(
                workflow=run.definition.name,
                phase_id=phase.id,
                voice=run.voice,
                instructions=list(phase.instructions),
            ),
        )
        requested_voices = (run.voice, *phase.calls_voices)
        delivered: set[str] = set()
        for called_voice in requested_voices:
            target = self._voice_target(called_voice)
            if target is None or target.casefold() in delivered:
                continue
            delivered.add(target.casefold())
            await self._emit(
                "voice_request",
                VoiceRequestData(
                    voice=target,
                    prompt="\n".join(phase.instructions),
                    workflow=run.definition.name,
                    phase_id=phase.id,
                ),
                target=target,
            )

    async def _emit(self, name: str, data: BaseModel, *, target: str | None = None) -> None:
        manager = self.manager
        if manager is not None:
            await manager.emit(name, data, source=self.name, target=target)

    def _voice_target(self, selected: str) -> str | None:
        manager = self.manager
        if manager is None:
            return None
        normalized = selected.casefold()
        from kateto.voices.base import VoiceProfile

        for plugin in manager.get_plugins():
            if plugin.name.casefold() == normalized:
                return plugin.name
            profile = getattr(plugin, "profile", None)
            if isinstance(profile, VoiceProfile) and profile.display_name.casefold() == normalized:
                return plugin.name
        return None

    @staticmethod
    def _key(workflow: str, voice: str) -> _WorkflowKey:
        return _WorkflowKey(workflow=workflow.casefold(), voice=voice.casefold())


def _failed_checkpoint(phase: WorkflowPhase, results: list[WorkflowCheckpointResult]) -> str | None:
    passed_by_checkpoint = {result.checkpoint.casefold(): result.passed for result in results}
    for checkpoint in phase.checkpoints:
        if passed_by_checkpoint.get(checkpoint.casefold()) is not True:
            return checkpoint
    return None
