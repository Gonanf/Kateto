from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core import Plugin, PluginManager, WorkflowEngine
from kateto.core.config import PluginSettings
from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    ProjectState,
    TranscriptionData,
    VoiceRequestData,
    WorkflowRunData,
)
from kateto.plugins.executor import ClassifierExecutor


class FixtureClassifier:
    def __init__(self, result: ClassificationData) -> None:
        self.result = result

    async def __aenter__(self) -> FixtureClassifier:
        return self

    async def aclose(self) -> None:
        return None

    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        return self.result.model_copy(update={"text": text})


class FixtureClassifierExecutor(ClassifierExecutor):
    def __init__(self, result: ClassificationData) -> None:
        super().__init__(settings=PluginSettings())
        self._fixture = FixtureClassifier(result)

    async def enable(self) -> None:
        self._classifier = self._fixture

    async def disable(self) -> None:
        self._classifier = None


class RecordingVoice(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name, capabilities=("voice",))
        self.requests: list[VoiceRequestData] = []
        self.generates: list[GenerateData] = []

    async def initialize(self) -> None:
        manager = self.manager
        assert manager is not None
        manager.register_event("voice_request", VoiceRequestData)
        manager.register_event("generate", GenerateData)

    async def on_voice_request(self, data: VoiceRequestData) -> None:
        self.requests.append(data)
        manager = self.manager
        assert manager is not None
        await manager.emit("generate", GenerateData(prompt=data.prompt), source="voice_request", target=self.name)

    async def on_generate(self, data: GenerateData) -> None:
        self.generates.append(data)


@pytest.mark.asyncio
async def test_classifier_routes_selected_voice_and_workflow() -> None:
    # Given: a classifier result selecting a concrete voice and workflow.
    manager = PluginManager()
    classifier = FixtureClassifierExecutor(
        ClassificationData(
            text="plan the sprint",
            category=Classification.EXECUTE,
            voice="doktor",
            workflow="sprint-planning",
        ),
    )
    await manager.enable_plugin(classifier)
    workflow_path = Path("/tmp/kateto-routing-workflow.py")
    workflow_path.write_text(
        "name = 'sprint-planning'\nphases = [{'id': 'plan', 'name': 'plan', 'instructions': ['plan']}]\n",
        encoding="utf-8",
    )
    engine = WorkflowEngine(config_dir=workflow_path.parent)
    await manager.enable_plugin(engine)
    await manager.enable_plugin(RecordingVoice("doktor"))

    try:
        # When: executable transcription enters the event bus.
        await manager.emit("transcription", TranscriptionData(text="plan the sprint"), source="fixture")
        await manager.wait_for_idle()

        # Then: workflow routing is targeted to the workflow owner with the selected voice preserved.
        workflow_events = [event for event in manager.get_events() if event.name == "workflow_run"]
        assert [
            (event.target, event.data.voice, event.data.workflow)
            for event in workflow_events
            if isinstance(event.data, WorkflowRunData)
        ] == [
            ("workflow_engine", "doktor", "sprint-planning"),
        ]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_existing_project_skips_initiation_workflow() -> None:
    # Given: the classifier identifies an already-underway project and initiation routing.
    manager = PluginManager()
    classifier = FixtureClassifierExecutor(
        ClassificationData(
            text="continue the existing project",
            category=Classification.EXECUTE,
            voice="jane",
            workflow="project-initiation",
            project_state=ProjectState.ALREADY_UNDERWAY,
        ),
    )
    await manager.enable_plugin(classifier)
    await manager.enable_plugin(RecordingVoice("jane"))

    try:
        # When: existing-project transcription is classified.
        await manager.emit("transcription", TranscriptionData(text="continue the existing project"), source="fixture")
        await manager.wait_for_idle()

        # Then: no initiation or requirements workflow is dispatched.
        assert not [event for event in manager.get_events() if event.name == "workflow_run"]
        assert not [event for event in manager.get_events() if event.name == "generate"]
    finally:
        await manager.close()


def _workflow(config_dir: Path) -> None:
    path = config_dir / "voices" / "jane" / "workflows" / "brief" / "workflow.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        "name = 'brief'\n"
        "description = 'brief'\n"
        "voice = 'Jane'\n"
        "phases = [{'id': 'ask', 'name': 'ask', 'instructions': ['ask'], 'calls_voices': ['Doktor']}]\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_workflow_calls_voices_through_typed_request_and_generate(tmp_path: Path) -> None:
    # Given: a workflow phase that calls Doktor and a receiving Doktor voice.
    _workflow(tmp_path)
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    doktor = RecordingVoice("doktor")
    await manager.enable_plugin(engine)
    await manager.enable_plugin(doktor)

    try:
        # When: the typed workflow command starts the phase.
        await manager.emit("workflow_run", WorkflowRunData(workflow="brief", voice="jane"), source="fixture")
        await manager.wait_for_idle()

        # Then: the called voice receives a typed request and a targeted generate event.
        assert [(request.voice, request.workflow, request.phase_id) for request in doktor.requests] == [
            ("doktor", "brief", "ask"),
        ]
        assert [event.target for event in manager.get_events() if event.name == "generate"] == ["doktor"]
        assert [generate.prompt for generate in doktor.generates] == ["ask"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_interrupt_stops_active_workflow(tmp_path: Path) -> None:
    # Given: an active workflow owned by the workflow engine.
    config_dir = tmp_path
    workflow_path = config_dir / "workflows" / "brief" / "workflow.py"
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(
        "name = 'brief'\nphases = [{'id': 'ask', 'name': 'ask', 'instructions': ['ask']}]\n",
        encoding="utf-8",
    )
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=config_dir)
    await manager.enable_plugin(engine)

    try:
        # When: an interrupt event reaches the workflow owner.
        await manager.emit("workflow_run", WorkflowRunData(workflow="brief", voice="jane"), source="fixture")
        await manager.wait_for_idle()
        await manager.interrupt(reason="new-speech")
        await manager.wait_for_idle()

        # Then: the run is cancelled and publishes its typed stopped event.
        snapshot = engine.snapshot(workflow="brief", voice="jane")
        assert snapshot is not None
        assert snapshot.status.value == "stopped"
        assert [event.name for event in manager.get_events() if event.name == "workflow_stopped"]
    finally:
        await manager.close()
