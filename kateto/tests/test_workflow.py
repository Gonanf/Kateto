from __future__ import annotations

from pathlib import Path

import pytest

import kateto.core as core
import kateto.core.event as event_contracts
from kateto.core.event import (
    VoiceIdleData,
    WorkflowCheckpointResult,
    WorkflowCheckpointFailData,
    WorkflowPhaseCompleteData,
    WorkflowPhaseStartData,
    WorkflowRunData,
    WorkflowStopData,
)
from kateto.core.workflow import (
    WorkflowCatalog,
    WorkflowDefinitionError,
    WorkflowPhaseStatus,
    WorkflowStatus,
)


def _workflow_source(name: str, phase_ids: tuple[str, ...], voice: str | None = None) -> str:
    voice_line = "" if voice is None else f"voice = {voice!r}\n"
    phases = ",\n".join(
        "    {"
        f"'id': {phase_id!r}, "
        f"'name': {phase_id!r}, "
        f"'instructions': ['perform {phase_id}'], "
        f"'deliverables': [{f'{phase_id}.md'!r}], "
        f"'checkpoints': [{f'{phase_id}-checked'!r}]"
        "}"
        for phase_id in phase_ids
    )
    return (
        f"name = {name!r}\n"
        "description = 'fixture workflow'\n"
        f"{voice_line}"
        "auto_advance = True\n"
        "can_stop = True\n"
        f"phases = [\n{phases}\n]\n"
    )


def _write_workflow(config_dir: Path, relative_path: Path, source: str) -> None:
    workflow_path = config_dir / relative_path
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(source, encoding="utf-8")


async def _enabled_engine(config_dir: Path) -> tuple[core.PluginManager, core.WorkflowEngine]:
    manager = core.PluginManager()
    engine = core.WorkflowEngine(config_dir=config_dir)
    await manager.enable_plugin(engine)
    return manager, engine


def test_workflow_engine_is_a_public_core_capability() -> None:
    # Given: a consumer importing the core package.
    # When: it requests the declarative workflow engine.
    # Then: the workflow owner is publicly available.
    assert hasattr(core, "WorkflowEngine")


def test_workflow_started_has_its_own_lifecycle_contract() -> None:
    # Given: a consumer that subscribes to workflow lifecycle events.
    # When: it inspects the started-event payload contract.
    # Then: starting is distinct from the workflow-run command.
    assert hasattr(event_contracts, "WorkflowStartedData")


def test_catalog_discovers_global_and_voice_workflows_and_reloads_edits(tmp_path: Path) -> None:
    # Given: global and Conquest-specific definitions with the same workflow name.
    _write_workflow(
        tmp_path,
        Path("workflows/shared/workflow.py"),
        _workflow_source("shared", ("global-phase",)),
    )
    voice_path = Path("voices/Conquest/workflows/shared/workflow.py")
    _write_workflow(tmp_path, voice_path, _workflow_source("shared", ("voice-phase",), "Conquest"))
    catalog = WorkflowCatalog(config_dir=tmp_path)

    # When: different voices discover the same named workflow, then its file changes.
    jane_definition = catalog.load(workflow="shared", voice="Jane")
    conquest_definition = catalog.load(workflow="shared", voice="Conquest")
    _write_workflow(tmp_path, voice_path, _workflow_source("shared", ("reloaded-phase",), "Conquest"))
    reloaded_definition = catalog.load(workflow="shared", voice="conquest")

    # Then: the voice override wins and every lookup reads the current declarative text.
    assert jane_definition.phases[0].id == "global-phase"
    assert conquest_definition.phases[0].id == "voice-phase"
    assert reloaded_definition.phases[0].id == "reloaded-phase"
    assert [(definition.name, definition.phases[0].id) for definition in catalog.discover(voice="Conquest")] == [
        ("shared", "reloaded-phase"),
    ]


@pytest.mark.asyncio
async def test_workflow_advances_only_after_idle_and_checkpoint_success(tmp_path: Path) -> None:
    # Given: a two-phase declarative workflow and its enabled event-bus owner.
    _write_workflow(
        tmp_path,
        Path("workflows/daily/workflow.py"),
        _workflow_source("daily", ("review", "publish")),
    )
    manager, engine = await _enabled_engine(tmp_path)

    try:
        # When: a phase completes successfully, then the assigned voice becomes idle.
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        await manager.wait_for_idle()
        await manager.emit("voice_idle", VoiceIdleData(voice="conquest"), source="conquest")
        await manager.wait_for_idle()
        before_completion = tuple(event.name for event in manager.get_events())
        await manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow="daily",
                phase_id="review",
                voice="Conquest",
                deliverables=["review.md"],
                checkpoint_results=[WorkflowCheckpointResult(checkpoint="review-checked", passed=True)],
            ),
            source="conquest",
        )
        await manager.wait_for_idle()
        completed_phase = engine.snapshot(workflow="daily", voice="Conquest")
        await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="conquest")
        await manager.wait_for_idle()
        await manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow="daily",
                phase_id="publish",
                voice="Conquest",
                deliverables=["publish.md"],
                checkpoint_results=[WorkflowCheckpointResult(checkpoint="publish-checked", passed=True)],
            ),
            source="conquest",
        )
        await manager.wait_for_idle()
        await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="conquest")
        await manager.wait_for_idle()

        # Then: a hung in-progress phase cannot advance, while each completed phase waits for idle.
        assert before_completion == ("workflow_run", "workflow_started", "workflow_phase_start", "voice_idle")
        assert completed_phase is not None
        assert completed_phase.status is WorkflowStatus.RUNNING
        assert completed_phase.phase_status is WorkflowPhaseStatus.DONE
        assert tuple(event.name for event in manager.get_events()) == (
            "workflow_run",
            "workflow_started",
            "workflow_phase_start",
            "voice_idle",
            "workflow_phase_complete",
            "voice_idle",
            "workflow_phase_start",
            "workflow_phase_complete",
            "voice_idle",
            "workflow_completed",
        )
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_checkpoint_failure_pauses_without_a_next_phase(tmp_path: Path) -> None:
    # Given: a two-phase workflow whose first checkpoint reports false.
    _write_workflow(
        tmp_path,
        Path("workflows/daily/workflow.py"),
        _workflow_source("daily", ("review", "publish")),
    )
    manager, engine = await _enabled_engine(tmp_path)

    try:
        # When: the voice reports the first phase complete with a failed checkpoint and becomes idle.
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        await manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow="daily",
                phase_id="review",
                voice="Conquest",
                checkpoint_results=[WorkflowCheckpointResult(checkpoint="review-checked", passed=False)],
            ),
            source="conquest",
        )
        await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="conquest")
        await manager.wait_for_idle()

        # Then: failure is observable, the phase stays open, and no next phase starts.
        snapshot = engine.snapshot(workflow="daily", voice="Conquest")
        failures = [
            event.data
            for event in manager.get_events()
            if event.name == "workflow_checkpoint_fail" and isinstance(event.data, WorkflowCheckpointFailData)
        ]
        starts = [
            event.data.phase_id
            for event in manager.get_events()
            if event.name == "workflow_phase_start" and isinstance(event.data, WorkflowPhaseStartData)
        ]
        assert snapshot is not None
        assert snapshot.status is WorkflowStatus.PAUSED
        assert snapshot.phase_status is WorkflowPhaseStatus.IN_PROGRESS
        assert [(failure.phase_id, failure.checkpoint) for failure in failures] == [("review", "review-checked")]
        assert starts == ["review"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_a_new_run_resumes_a_workflow(tmp_path: Path) -> None:
    # Given: an active workflow with a stop-capable declarative definition.
    _write_workflow(tmp_path, Path("workflows/daily/workflow.py"), _workflow_source("daily", ("review",)))
    manager, engine = await _enabled_engine(tmp_path)

    try:
        # When: the same workflow receives repeated stops, followed by a fresh run request.
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        stop = WorkflowStopData(workflow="daily", voice="Conquest", reason="user_cancelled")
        await manager.emit("workflow_stop", stop, source="conquest")
        await manager.emit("workflow_stop", stop, source="conquest")
        await manager.wait_for_idle()
        stopped = engine.snapshot(workflow="daily", voice="Conquest")
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        await manager.wait_for_idle()

        # Then: one stop lifecycle event occurs and a new run starts from the first phase.
        assert stopped is not None
        assert stopped.status is WorkflowStatus.STOPPED
        assert stopped.phase_status is WorkflowPhaseStatus.CANCELLED
        assert [event.name for event in manager.get_events()].count("workflow_stopped") == 1
        restarted = engine.snapshot(workflow="daily", voice="Conquest")
        assert restarted is not None
        assert restarted.status is WorkflowStatus.RUNNING
        assert restarted.phase_id == "review"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_stopped_run_reload_uses_the_current_declarative_definition(tmp_path: Path) -> None:
    # Given: a stopped run whose workflow definition is edited before it is started again.
    workflow_path = tmp_path / "workflows" / "daily" / "workflow.py"
    _write_workflow(tmp_path, workflow_path.relative_to(tmp_path), _workflow_source("daily", ("old",)))
    manager, engine = await _enabled_engine(tmp_path)

    try:
        # When: the run is cancelled, the source is reloaded, and the workflow is resumed.
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        await manager.emit(
            "workflow_stop",
            WorkflowStopData(workflow="daily", voice="Conquest", reason="cancelled"),
            source="fixture",
        )
        await manager.wait_for_idle()
        _write_workflow(tmp_path, workflow_path.relative_to(tmp_path), _workflow_source("daily", ("new",)))
        await manager.emit("workflow_run", WorkflowRunData(workflow="daily", voice="Conquest"), source="fixture")
        await manager.wait_for_idle()

        # Then: the resumed run starts from the current file, not stale in-memory instructions.
        snapshot = engine.snapshot(workflow="daily", voice="Conquest")
        starts = [
            event.data.phase_id
            for event in manager.get_events()
            if event.name == "workflow_phase_start" and isinstance(event.data, WorkflowPhaseStartData)
        ]
        assert snapshot is not None
        assert snapshot.phase_id == "new"
        assert starts == ["old", "new"]
    finally:
        await manager.close()


def test_catalog_rejects_untrusted_or_imperative_definition_text_without_execution(tmp_path: Path) -> None:
    # Given: a workflow.py file that tries to perform an imperative filesystem side effect.
    marker = tmp_path / "executed.txt"
    _write_workflow(
        tmp_path,
        Path("workflows/untrusted/workflow.py"),
        f"import pathlib\npathlib.Path({str(marker)!r}).write_text('owned')\n",
    )
    catalog = WorkflowCatalog(config_dir=tmp_path)

    # When: the catalog parses the untrusted definition at its boundary.
    with pytest.raises(WorkflowDefinitionError):
        catalog.load(workflow="untrusted", voice="Conquest")

    # Then: non-declarative text is rejected and no host-side code has run.
    assert not marker.exists()


def test_catalog_rejects_phase_run_scripts(tmp_path: Path) -> None:
    # Given: a literal workflow definition with an imperative phase run entry.
    _write_workflow(
        tmp_path,
        Path("workflows/hybrid/workflow.py"),
        "name = 'hybrid'\nphases = [{'id': 'phase', 'name': 'phase', 'instructions': ['work'], 'run': 'echo no'}]\n",
    )

    # When: the catalog parses the otherwise well-formed definition.
    with pytest.raises(WorkflowDefinitionError):
        WorkflowCatalog(config_dir=tmp_path).load(workflow="hybrid", voice="Conquest")

    # Then: workflow phases remain declarative and cannot contain scripts.


def test_catalog_wraps_malformed_literal_evaluation_as_definition_error(tmp_path: Path) -> None:
    # Given: a definition whose declaration is executable-looking rather than literal data.
    _write_workflow(
        tmp_path,
        Path("workflows/malformed/workflow.py"),
        "name = dict()\nphases = []\n",
    )

    # When: the catalog parses the untrusted declaration.
    with pytest.raises(WorkflowDefinitionError, match="literal value"):
        WorkflowCatalog(config_dir=tmp_path).load(workflow="malformed", voice="Conquest")

    # Then: callers receive the typed catalog error, never an implementation exception.


def test_catalog_rejects_workflow_symlink_outside_config_root(tmp_path: Path) -> None:
    # Given: a workflow path that resolves outside the configured declarative root.
    outside = tmp_path / "outside"
    _write_workflow(outside, Path("workflow/workflow.py"), _workflow_source("escape", ("phase",)))
    workflow_dir = tmp_path / "workflows" / "escape"
    workflow_dir.parent.mkdir(parents=True, exist_ok=True)
    workflow_dir.symlink_to(outside / "workflow", target_is_directory=True)

    # When: the catalog resolves the workflow selected by name.
    with pytest.raises(WorkflowDefinitionError, match="escapes workflow root"):
        WorkflowCatalog(config_dir=tmp_path).load(workflow="escape", voice="Conquest")

    # Then: definitions cannot make the catalog read files outside its config root.


def test_catalog_rejects_symlinked_voice_root_outside_config_root(tmp_path: Path) -> None:
    # Given: a Conquest voice directory symlinked to a location outside the config root.
    outside = tmp_path / "outside" / "Conquest"
    _write_workflow(outside, Path("workflows/daily/workflow.py"), _workflow_source("daily", ("escape",), "Conquest"))
    voice_link = tmp_path / "voices" / "Conquest"
    voice_link.parent.mkdir(parents=True, exist_ok=True)
    try:
        voice_link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink fixture unavailable: {error}")

    # When: the catalog loads a workflow for the symlinked voice.
    with pytest.raises(WorkflowDefinitionError, match="voice directory escapes config root"):
        WorkflowCatalog(config_dir=tmp_path).load(workflow="daily", voice="Conquest")

    # Then: workflow definitions cannot be loaded through an escaped voice root.
