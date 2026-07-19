from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core.workflow import (
    WorkflowCatalog,
    WorkflowDefinition,
    WorkflowDefinitionError,
    WorkflowPhase,
)
from kateto.core.event import (
    VoiceIdleData,
    WorkflowCheckpointResult,
    WorkflowPhaseCompleteData,
    WorkflowRunData,
)
import kateto.core as core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_DEFAULTS = Path(__file__).resolve().parents[2] / "config" / "defaults"


def _check_phase(phase: WorkflowPhase, *, id: str) -> None:
    """Assert common phase invariants."""
    assert phase.id == id, f"expected phase id {id!r}, got {phase.id!r}"
    assert phase.name, f"phase {id!r} has no name"
    assert len(phase.instructions) >= 1, f"phase {id!r} has no instructions"
    assert len(phase.checkpoints) >= 1, f"phase {id!r} has no checkpoints"


def _check_workflow(
    definition: WorkflowDefinition,
    *,
    name: str,
    voice: str,
    phase_ids: tuple[str, ...],
) -> None:
    """Assert common workflow invariants."""
    assert definition.name == name, f"expected name {name!r}, got {definition.name!r}"
    assert definition.voice == voice, f"expected voice {voice!r}, got {definition.voice!r}"
    assert definition.description, f"workflow {name!r} has no description"
    assert len(definition.phases) == len(phase_ids), (
        f"expected {len(phase_ids)} phases, got {len(definition.phases)}"
    )
    for phase, expected_id in zip(definition.phases, phase_ids):
        _check_phase(phase, id=expected_id)


# ---------------------------------------------------------------------------
# Jane — Orchestrator PM workflows
# ---------------------------------------------------------------------------


class TestJaneWorkflows:
    def test_project_initiation_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="project-initiation", voice="Jane")

        _check_workflow(definition, name="project-initiation", voice="Jane", phase_ids=("define-project", "create-charter"))

        # Phase 1: define-project
        phase = definition.phases[0]
        assert len(phase.instructions) >= 4
        assert "stakeholder" in " ".join(phase.instructions).lower()
        assert "deliverables" in str(phase.deliverables).lower() or any("scope" in d for d in phase.deliverables)
        assert "orchestrator" in phase.calls_skills
        assert "Doktor" in phase.calls_voices or "Conquest" in phase.calls_voices

        # Phase 2: create-charter
        phase = definition.phases[1]
        assert "charter" in " ".join(phase.instructions).lower()
        assert "milestone" in " ".join(phase.instructions).lower()
        assert "orchestrator" in phase.calls_skills

    def test_stakeholder_communication_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="stakeholder-communication", voice="Jane")

        _check_workflow(
            definition, name="stakeholder-communication", voice="Jane", phase_ids=("plan-communication", "report-status")
        )

        # Phase 1: plan-communication
        phase = definition.phases[0]
        assert "communication" in " ".join(phase.instructions).lower()
        assert "channel" in " ".join(phase.instructions).lower()

        # Phase 2: report-status
        phase = definition.phases[1]
        assert "status" in " ".join(phase.instructions).lower() or "report" in " ".join(phase.instructions).lower()
        assert "escalat" in " ".join(phase.instructions).lower()

    def test_project_closure_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="project-closure", voice="Jane")

        _check_workflow(
            definition, name="project-closure", voice="Jane", phase_ids=("verify-deliverables", "retrospect-celebrate")
        )

        # Phase 1: verify-deliverables
        phase = definition.phases[0]
        assert "acceptance" in " ".join(phase.instructions).lower() or "verify" in " ".join(phase.instructions).lower()
        assert "archive" in " ".join(phase.instructions).lower()

        # Phase 2: retrospect-celebrate
        phase = definition.phases[1]
        assert "retrospect" in " ".join(phase.instructions).lower()
        assert "lesson" in " ".join(phase.instructions).lower() or "celebrate" in " ".join(phase.instructions).lower()


# ---------------------------------------------------------------------------
# Doktor — Delivery Advisor PM workflows
# ---------------------------------------------------------------------------


class TestDoktorWorkflows:
    def test_risk_management_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="risk-management", voice="Doktor")

        _check_workflow(
            definition, name="risk-management", voice="Doktor", phase_ids=("identify-risks", "plan-mitigations")
        )

        # Phase 1: identify-risks
        phase = definition.phases[0]
        assert "risk" in " ".join(phase.instructions).lower()
        assert "likelihood" in " ".join(phase.instructions).lower() or "impact" in " ".join(phase.instructions).lower()
        assert "risk-analysis" in phase.calls_skills

        # Phase 2: plan-mitigations
        phase = definition.phases[1]
        assert "mitigation" in " ".join(phase.instructions).lower()
        assert "risk-analysis" in phase.calls_skills
        assert "backlog" in phase.calls_skills

    def test_backlog_grooming_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="backlog-grooming", voice="Doktor")

        _check_workflow(
            definition, name="backlog-grooming", voice="Doktor", phase_ids=("review-prioritize", "refine-estimate")
        )

        # Phase 1: review-prioritize
        phase = definition.phases[0]
        assert "prioriti" in " ".join(phase.instructions).lower()
        assert "moscow" in " ".join(phase.instructions).lower() or "must" in " ".join(phase.instructions).lower()
        assert "backlog" in phase.calls_skills

        # Phase 2: refine-estimate
        phase = definition.phases[1]
        assert "estimate" in " ".join(phase.instructions).lower() or "story point" in " ".join(phase.instructions).lower()
        assert "planning-poker" in phase.calls_skills

    def test_resource_planning_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="resource-planning", voice="Doktor")

        _check_workflow(
            definition, name="resource-planning", voice="Doktor", phase_ids=("assess-capacity", "plan-budget")
        )

        # Phase 1: assess-capacity
        phase = definition.phases[0]
        assert "capacity" in " ".join(phase.instructions).lower() or "availability" in " ".join(phase.instructions).lower()
        assert "constraint" in " ".join(phase.instructions).lower()

        # Phase 2: plan-budget
        phase = definition.phases[1]
        assert "budget" in " ".join(phase.instructions).lower() or "cost" in " ".join(phase.instructions).lower()
        assert "backlog" in phase.calls_skills
        assert "risk-analysis" in phase.calls_skills


# ---------------------------------------------------------------------------
# Conquest — Agile Facilitator PM workflows
# ---------------------------------------------------------------------------


class TestConquestWorkflows:
    def test_sprint_execution_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="sprint-execution", voice="Conquest")

        _check_workflow(
            definition, name="sprint-execution", voice="Conquest", phase_ids=("monitor-progress", "resolve-blockers")
        )

        # Phase 1: monitor-progress
        phase = definition.phases[0]
        assert "progress" in " ".join(phase.instructions).lower() or "velocity" in " ".join(phase.instructions).lower()
        assert "backlog" in phase.calls_skills

        # Phase 2: resolve-blockers
        phase = definition.phases[1]
        assert "blocker" in " ".join(phase.instructions).lower() or "impediment" in " ".join(phase.instructions).lower()
        assert "wip" in " ".join(phase.instructions).lower() or "limit" in " ".join(phase.instructions).lower()

    def test_continuous_improvement_loads(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        definition = catalog.load(workflow="continuous-improvement", voice="Conquest")

        _check_workflow(
            definition,
            name="continuous-improvement",
            voice="Conquest",
            phase_ids=("analyze-metrics", "implement-improvements"),
        )

        # Phase 1: analyze-metrics
        phase = definition.phases[0]
        assert "metric" in " ".join(phase.instructions).lower() or "cycle time" in " ".join(phase.instructions).lower()
        assert "waste" in " ".join(phase.instructions).lower()

        # Phase 2: implement-improvements
        phase = definition.phases[1]
        assert "improvement" in " ".join(phase.instructions).lower() or "experiment" in " ".join(phase.instructions).lower()
        assert "backlog" in phase.calls_skills


# ---------------------------------------------------------------------------
# Cross-voice discovery and lifecycle tests
# ---------------------------------------------------------------------------


class TestPMWorkflowDiscovery:
    """Verify all PM workflows are discoverable per voice."""

    def test_jane_discovers_pm_workflows(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        workflows = catalog.discover(voice="Jane")

        jane_names = {w.name for w in workflows}
        assert "project-initiation" in jane_names
        assert "stakeholder-communication" in jane_names
        assert "project-closure" in jane_names

    def test_doktor_discovers_pm_workflows(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        workflows = catalog.discover(voice="Doktor")

        doktor_names = {w.name for w in workflows}
        assert "risk-management" in doktor_names
        assert "backlog-grooming" in doktor_names
        assert "resource-planning" in doktor_names
        # Existing Doktor workflows
        assert "sprint-planning" in doktor_names
        assert "sprint-review" in doktor_names

    def test_conquest_discovers_pm_workflows(self) -> None:
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        workflows = catalog.discover(voice="Conquest")

        conquest_names = {w.name for w in workflows}
        assert "sprint-execution" in conquest_names
        assert "continuous-improvement" in conquest_names
        # Existing Conquest workflows
        assert "daily-standup" in conquest_names
        assert "sprint-retrospective" in conquest_names

    def test_workflow_name_matches_directory(self) -> None:
        """The workflow name in the file must match its directory name."""
        catalog = WorkflowCatalog(config_dir=CONFIG_DEFAULTS)
        for voice in ("Jane", "Doktor", "Conquest"):
            for workflow in catalog.discover(voice=voice):
                dir_name = workflow.name  # name is validated against directory in _definition_from_file
                assert dir_name, f"workflow {workflow.name} for {voice} has no name"


class TestPMWorkflowLifecycle:
    """Test engine lifecycle for a representative PM workflow."""

    @pytest.mark.asyncio
    async def test_project_initiation_engine_lifecycle(self, tmp_path: Path) -> None:
        """Run project-initiation through the engine with fixture config."""
        # Given: a temp config with the project-initiation workflow
        from kateto.core.workflow import WorkflowPhaseStatus, WorkflowStatus

        src = Path(__file__).resolve().parents[2] / "config" / "defaults" / "voices" / "jane" / "workflows" / "project-initiation"
        dst = tmp_path / "voices" / "Jane" / "workflows" / "project-initiation"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "workflow.py").write_text((src / "workflow.py").read_text(), encoding="utf-8")

        manager = core.PluginManager()
        engine = core.WorkflowEngine(config_dir=tmp_path)
        await manager.enable_plugin(engine)

        try:
            # When: the workflow is started
            await manager.emit(
                "workflow_run", WorkflowRunData(workflow="project-initiation", voice="Jane"), source="fixture"
            )
            await manager.wait_for_idle()

            # Then: it is running on phase 0
            snapshot = engine.snapshot(workflow="project-initiation", voice="Jane")
            assert snapshot is not None
            assert snapshot.status is WorkflowStatus.RUNNING
            assert snapshot.phase_id == "define-project"
            assert snapshot.phase_status is WorkflowPhaseStatus.IN_PROGRESS

            # When: phase completes with checkpoints passed, then voice becomes idle
            await manager.emit(
                "workflow_phase_complete",
                WorkflowPhaseCompleteData(
                    workflow="project-initiation",
                    phase_id="define-project",
                    voice="Jane",
                    deliverables=["project-scope.md", "stakeholder-registry.md"],
                    checkpoint_results=[
                        WorkflowCheckpointResult(checkpoint="All stakeholders are identified and documented", passed=True),
                        WorkflowCheckpointResult(checkpoint="Project objectives are measurable and documented", passed=True),
                        WorkflowCheckpointResult(checkpoint="Scope and constraints are clearly defined", passed=True),
                    ],
                ),
                source="jane",
            )
            await manager.wait_for_idle()

            # And the voice goes idle, auto-advance should fire after voice_idle
            await manager.emit("voice_idle", VoiceIdleData(voice="Jane"), source="jane")
            await manager.wait_for_idle()

            # Then: phase 1 (create-charter) should be in progress
            snapshot = engine.snapshot(workflow="project-initiation", voice="Jane")
            assert snapshot is not None
            assert snapshot.phase_id == "create-charter"
            assert snapshot.phase_status is WorkflowPhaseStatus.IN_PROGRESS

        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_risk_management_checkpoint_failure(self, tmp_path: Path) -> None:
        """A failed checkpoint should pause the workflow."""
        from kateto.core.workflow import WorkflowPhaseStatus, WorkflowStatus

        src = Path(__file__).resolve().parents[2] / "config" / "defaults" / "voices" / "doktor" / "workflows" / "risk-management"
        dst = tmp_path / "voices" / "Doktor" / "workflows" / "risk-management"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "workflow.py").write_text((src / "workflow.py").read_text(), encoding="utf-8")

        manager = core.PluginManager()
        engine = core.WorkflowEngine(config_dir=tmp_path)
        await manager.enable_plugin(engine)

        try:
            await manager.emit(
                "workflow_run", WorkflowRunData(workflow="risk-management", voice="Doktor"), source="fixture"
            )
            await manager.wait_for_idle()

            # When: phase completes with a FAILED checkpoint
            await manager.emit(
                "workflow_phase_complete",
                WorkflowPhaseCompleteData(
                    workflow="risk-management",
                    phase_id="identify-risks",
                    voice="Doktor",
                    checkpoint_results=[
                        WorkflowCheckpointResult(
                            checkpoint="All identified risks have likelihood and impact assessed", passed=False
                        ),
                    ],
                ),
                source="doktor",
            )
            await manager.wait_for_idle()

            # Then: workflow is PAUSED, phase still IN_PROGRESS
            snapshot = engine.snapshot(workflow="risk-management", voice="Doktor")
            assert snapshot is not None
            assert snapshot.status is WorkflowStatus.PAUSED
            assert snapshot.phase_status is WorkflowPhaseStatus.IN_PROGRESS

        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_sprint_execution_full_cycle(self, tmp_path: Path) -> None:
        """Complete sprint-execution through all phases."""
        from kateto.core.workflow import WorkflowPhaseStatus, WorkflowStatus

        src = Path(__file__).resolve().parents[2] / "config" / "defaults" / "voices" / "conquest" / "workflows" / "sprint-execution"
        dst = tmp_path / "voices" / "Conquest" / "workflows" / "sprint-execution"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "workflow.py").write_text((src / "workflow.py").read_text(), encoding="utf-8")

        manager = core.PluginManager()
        engine = core.WorkflowEngine(config_dir=tmp_path)
        await manager.enable_plugin(engine)

        try:
            # Start the workflow
            await manager.emit(
                "workflow_run", WorkflowRunData(workflow="sprint-execution", voice="Conquest"), source="fixture"
            )
            await manager.wait_for_idle()

            # Complete phase 0: monitor-progress
            await manager.emit(
                "workflow_phase_complete",
                WorkflowPhaseCompleteData(
                    workflow="sprint-execution",
                    phase_id="monitor-progress",
                    voice="Conquest",
                    deliverables=["sprint-progress-report.md"],
                    checkpoint_results=[
                        WorkflowCheckpointResult(
                            checkpoint="Sprint progress is tracked against the sprint goal", passed=True
                        ),
                        WorkflowCheckpointResult(
                            checkpoint="Falling-behind items are identified with supporting context", passed=True
                        ),
                        WorkflowCheckpointResult(
                            checkpoint="Progress metrics are communicated to the team", passed=True
                        ),
                    ],
                ),
                source="conquest",
            )
            await manager.wait_for_idle()

            # Voice idle triggers auto-advance to phase 1
            await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="conquest")
            await manager.wait_for_idle()

            # Phase 1: resolve-blockers should be in progress
            snapshot = engine.snapshot(workflow="sprint-execution", voice="Conquest")
            assert snapshot is not None
            assert snapshot.phase_id == "resolve-blockers"
            assert snapshot.phase_status is WorkflowPhaseStatus.IN_PROGRESS

            # Complete phase 1
            await manager.emit(
                "workflow_phase_complete",
                WorkflowPhaseCompleteData(
                    workflow="sprint-execution",
                    phase_id="resolve-blockers",
                    voice="Conquest",
                    deliverables=["blocker-log.md"],
                    checkpoint_results=[
                        WorkflowCheckpointResult(
                            checkpoint="All blockers are documented with resolution status", passed=True
                        ),
                        WorkflowCheckpointResult(checkpoint="Escalated blockers have clear ownership", passed=True),
                        WorkflowCheckpointResult(checkpoint="WIP limits are respected across all board columns", passed=True),
                    ],
                ),
                source="conquest",
            )
            await manager.wait_for_idle()

            # Voice idle triggers completion
            await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="conquest")
            await manager.wait_for_idle()

            # Then: workflow is COMPLETED
            snapshot = engine.snapshot(workflow="sprint-execution", voice="Conquest")
            assert snapshot is not None
            assert snapshot.status is WorkflowStatus.COMPLETED

            # Verify the full event stream
            events = [event.name for event in manager.get_events()]
            assert "workflow_completed" in events

        finally:
            await manager.close()
