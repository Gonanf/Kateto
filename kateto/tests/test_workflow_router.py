from __future__ import annotations

from pathlib import Path

import pytest
from typing import override

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings, load_config
from kateto.core.discovery import DiscoveryContext
from kateto.core.event import Classification, ClassificationData, GenerateData, VoiceRequestData, WorkflowRunData
from kateto.core.workflow_engine import WorkflowEngine
from kateto.plugins.executor.workflow_router import WorkflowRouter, WorkflowSelector
from kateto.providers._models import WorkflowCandidate
from kateto.providers.classifier import WorkflowSelection


class _FakeProvider:
    async def __aenter__(self) -> _FakeProvider:
        return self

    async def aclose(self) -> None:
        return None

    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        assert text == "start a new project"
        assert candidates[0].name == "project-initiation"
        return WorkflowSelection(name="project-initiation", voice="jane", confidence=0.9)


class _TestableWorkflowRouter(WorkflowRouter):
    _provider: WorkflowSelector | None

    @override
    async def enable(self) -> None:
        self._provider = _FakeProvider()


class _VoicePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("jane", capabilities=("voice",))
        self.prompts: list[str] = []

    async def on_voice_request(self, data: VoiceRequestData) -> None:
        self.prompts.append(data.prompt)
        manager = self.manager
        assert manager is not None
        _ = await manager.emit(
            "generate",
            GenerateData(prompt=data.prompt),
            source=self.name,
            target=self.name,
        )


def _write_workflow(config_dir: Path) -> None:
    workflow_dir = config_dir / "workflows" / "project-initiation"
    workflow_dir.mkdir(parents=True)
    _ = (workflow_dir / "workflow.py").write_text(
        (
            "name = 'project-initiation'\n"
            "description = 'Start a new project and gather requirements.'\n"
            "phases = [{'id': 'start', 'name': 'Start', 'instructions': ['Gather requirements']}]\n"
        ),
        encoding="utf-8",
    )


def test_existing_config_without_router_section_still_discovers_the_router(tmp_path: Path) -> None:
    _ = (tmp_path / "config.toml").write_text(
        "[kateto]\n"
        "[plugin.executor_classifier]\n"
        "enabled = true\n"
        "model_endpoint = 'http://classifier.test'\n"
        "model = 'classifier'\n"
        "[cli]\n"
        "allowlist = ['echo']\n",
        encoding="utf-8",
    )
    context = DiscoveryContext(
        config=load_config(config_dir=tmp_path),
        shared={},
    )

    from kateto.plugins.executor import create_plugins

    assert {plugin.name for plugin in create_plugins(context)} >= {
        "executor_classifier",
        "executor_workflow_router",
    }


def test_new_project_requests_prefer_project_initiation() -> None:
    router = WorkflowRouter(PluginSettings(model_endpoint="http://classifier.test", model="classifier"))
    data = ClassificationData(
        text="Vamos a empezar un nuevo proyecto",
        category=Classification.EXECUTE,
    )
    candidates = (
        WorkflowCandidate(name="project-initiation", voice="jane", description="Start a project"),
        WorkflowCandidate(name="stakeholder-communication", voice="jane", description="Communicate with stakeholders"),
    )

    selection = router._new_project_selection(data, candidates)

    assert selection is not None
    assert selection.name == "project-initiation"


@pytest.mark.asyncio
async def test_workflow_router_runs_the_selected_dynamic_workflow(tmp_path: Path) -> None:
    _write_workflow(tmp_path)
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    router = _TestableWorkflowRouter(
        PluginSettings(model_endpoint="http://classifier.test", model="classifier"),
    )
    await manager.enable_plugin(engine)
    voice = _VoicePlugin()
    await manager.enable_plugin(voice)
    await manager.enable_plugin(router)
    try:
        _ = await manager.emit(
            "classification",
            ClassificationData(text="start a new project", category=Classification.EXECUTE),
            source="executor_classifier",
        )
        await manager.wait_for_idle()
    finally:
        await manager.close()

    runs = [event.data for event in manager.get_events() if event.name == "workflow_run"]
    assert runs == [
        WorkflowRunData(
            workflow="project-initiation",
            voice="jane",
            context={"project_state": "new", "confidence": 1.0},
        ),
    ]
    assert voice.prompts == ["Gather requirements"]
    assert [event.name for event in manager.get_events()] == [
        "classification",
        "workflow_run",
        "workflow_started",
        "workflow_phase_start",
        "voice_request",
        "generate",
    ]
