from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from kateto.core import Plugin, PluginManager, WorkflowEngine
from kateto.core.config import PluginSettings, VoiceSettings
from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    ProjectState,
    TranscriptionData,
    VoiceRequestData,
    VoiceEnableData,
    VoiceEnabledData,
    WorkflowRunData,
)
from kateto.plugins.executor import ClassifierExecutor
from kateto.plugins.executor.workflow_router import WorkflowRouter
from kateto.providers._models import WorkflowCandidate
from kateto.providers.classifier import WorkflowSelection
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole


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


class _FakeSelector:
    """Deterministic WorkflowSelector stub for router tests."""

    def __init__(self, selection: WorkflowSelection | None) -> None:
        self.selection = selection
        self.calls: list[str] = []

    async def __aenter__(self) -> _FakeSelector:
        return self

    async def aclose(self) -> None:
        return None

    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        self.calls.append(text)
        return self.selection


class FixtureWorkflowRouter(WorkflowRouter):
    def __init__(self, selection: WorkflowSelection | None) -> None:
        super().__init__(settings=PluginSettings())
        self._fake = _FakeSelector(selection)

    async def enable(self) -> None:
        self._provider = self._fake


class VoiceEnabler(Plugin):
    def __init__(self, voice: RecordingVoice) -> None:
        super().__init__("voice_manager")
        self.voice = voice

    async def initialize(self) -> None:
        manager = self.manager
        assert manager is not None
        manager.register_event("voice_enable", VoiceEnableData)
        manager.register_event("voice_enabled", VoiceEnabledData)

    async def on_voice_enable(self, data: VoiceEnableData) -> None:
        manager = self.manager
        assert manager is not None
        if data.voice_name.casefold() == self.voice.name.casefold():
            await manager.enable_plugin(self.voice)
            await manager.emit(
                "voice_enabled",
                VoiceEnabledData(voice_name=self.voice.name),
                source=self.name,
            )


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


def _write_reference(config_dir: Path, voice: str) -> None:
    reference = config_dir / "voices" / voice / "reference.wav"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(b"RIFFfixtureWAVE")


def _write_workflow(config_dir: Path, voice: str, name: str, description: str = "wf") -> None:
    path = config_dir / "voices" / voice / "workflows" / name / "workflow.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"name = '{name}'\n"
        f"description = '{description}'\n"
        f"voice = '{voice}'\n"
        "phases = [{'id': 'plan', 'name': 'plan', 'instructions': ['plan']}]\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_router_routes_selected_voice_and_workflow(tmp_path: Path) -> None:
    # Given: a workflow selection choosing doktor's sprint-planning workflow.
    _write_workflow(tmp_path, "doktor", "sprint-planning")
    manager = PluginManager()
    router = FixtureWorkflowRouter(WorkflowSelection(name="sprint-planning", voice="doktor", confidence=0.9))
    await manager.enable_plugin(router)
    await manager.enable_plugin(WorkflowEngine(config_dir=tmp_path))
    await manager.enable_plugin(RecordingVoice("doktor"))

    try:
        # When: an executable classification enters the event bus.
        await manager.emit(
            "classification",
            ClassificationData(text="plan the sprint", category=Classification.EXECUTE, voice="doktor"),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: workflow routing is targeted to the workflow engine with the selected voice preserved.
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
    # Given: an already-underway project and an initiation-workflow selection.
    manager = PluginManager()
    router = FixtureWorkflowRouter(WorkflowSelection(name="project-initiation", voice="jane", confidence=0.9))
    await manager.enable_plugin(router)
    await manager.enable_plugin(RecordingVoice("jane"))

    try:
        # When: existing-project classification is routed.
        await manager.emit(
            "classification",
            ClassificationData(
                text="continue the existing project",
                category=Classification.EXECUTE,
                voice="jane",
                project_state=ProjectState.ALREADY_UNDERWAY,
            ),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: no initiation or requirements workflow is dispatched; the turn degrades to plain generation.
        assert not [event for event in manager.get_events() if event.name == "workflow_run"]
        generate_events = [event for event in manager.get_events() if event.name == "generate"]
        assert [event.target for event in generate_events] == ["jane"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_new_project_without_selection_starts_project_initiation(tmp_path: Path) -> None:
    # Given: a new-project classification whose selector omitted the available workflow.
    _write_workflow(tmp_path, "jane", "project-initiation", "Start a new project")
    manager = PluginManager()
    router = FixtureWorkflowRouter(None)
    await manager.enable_plugin(router)
    await manager.enable_plugin(WorkflowEngine(config_dir=tmp_path))
    await manager.enable_plugin(RecordingVoice("jane"))

    try:
        # When: the new-project transcription is classified.
        await manager.emit(
            "classification",
            ClassificationData(
                text="I started a new project for a customer",
                category=Classification.EXECUTE,
                voice="jane",
                project_state=ProjectState.NEW,
            ),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: the deterministic project-initiation workflow is dispatched to Jane.
        workflow_events = [
            (event.target, event.data)
            for event in manager.get_events()
            if event.name == "workflow_run"
        ]
        assert [
            (target, data.workflow, data.voice)
            for target, data in workflow_events
            if isinstance(data, WorkflowRunData)
        ] == [
            ("workflow_engine", "project-initiation", "jane"),
        ]
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
async def test_workflow_enables_disabled_called_voice_before_request(tmp_path: Path) -> None:
    _workflow(tmp_path)
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    doktor = RecordingVoice("doktor")
    enabler = VoiceEnabler(doktor)
    await manager.enable_plugin(engine)
    await manager.enable_plugin(enabler)

    try:
        await manager.emit("workflow_run", WorkflowRunData(workflow="brief", voice="jane"), source="fixture")
        await manager.wait_for_idle()

        assert doktor.enabled
        assert [request.voice for request in doktor.requests] == ["doktor"]
        assert [event.name for event in manager.get_events()] == [
            "workflow_run",
            "workflow_started",
            "workflow_phase_start",
            "voice_enable",
            "voice_enabled",
            "voice_request",
            "generate",
        ]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_workflow_calls_real_voice_provider_for_automatic_request(tmp_path: Path) -> None:
    # Given: a workflow phase that calls a real batch VoiceAgent.
    _workflow(tmp_path)
    _write_reference(tmp_path, "doktor")
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    provider = RecordingProvider()
    doktor = VoiceAgent(
        profile=VoiceProfile(
            voice_id="doktor",
            display_name="Doktor",
            role=VoiceRole.DELIVERY_ADVISOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    await manager.enable_plugin(engine)
    await manager.enable_plugin(doktor)

    try:
        # When: the workflow starts and emits its automatic voice request.
        await manager.emit("workflow_run", WorkflowRunData(workflow="brief", voice="jane"), source="fixture")
        await manager.wait_for_idle()

        # Then: the targeted request reaches the provider with event-derived history.
        assert len(provider.requests) == 1
        assert [message.content for message in provider.requests[0].messages].count("ask") == 1
        assert [event.target for event in manager.get_events() if event.name == "generate"] == ["doktor"]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_interrupt_does_not_stop_active_workflow(tmp_path: Path) -> None:
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

        # Then: interruption cancels generation only; workflow state remains active.
        snapshot = engine.snapshot(workflow="brief", voice="jane")
        assert snapshot is not None
        assert snapshot.status.value == "running"
        assert not [event.name for event in manager.get_events() if event.name == "workflow_stopped"]
    finally:
        await manager.close()
