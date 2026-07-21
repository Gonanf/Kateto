from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, assert_never, override

from kateto.core.config import PluginSettings
from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    ProjectState,
    TranscriptionData,
    WorkflowRunData,
)
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.core.workflow_engine import WorkflowEngine

if TYPE_CHECKING:
    class ClassifierProtocol(Protocol):
        async def __aenter__(self) -> ClassifierProtocol: ...

        async def classify(
            self,
            text: str,
            *,
            agents: tuple[str, ...] = (),
            workflows: tuple[str, ...] = (),
        ) -> ClassificationData: ...

        async def aclose(self) -> None: ...


class ClassifierExecutor(Plugin):
    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("executor_classifier", receive_self_events=True)
        self._settings: PluginSettings = settings
        self._classifier: ClassifierProtocol | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("classification", ClassificationData)
        manager.register_event("generate", GenerateData)

    @override
    async def enable(self) -> None:
        from kateto.providers import ClassifierProvider

        classifier = ClassifierProvider(self._settings)
        self._classifier = await classifier.__aenter__()

    @override
    async def disable(self) -> None:
        if self._classifier is not None:
            await self._classifier.aclose()
            self._classifier = None

    async def on_transcription(self, data: TranscriptionData) -> None:
        classifier = self._classifier
        if classifier is None:
            msg = "classifier executor must be enabled before use"
            raise RuntimeError(msg)
        agents = self._collect_agent_names()
        workflows = self._collect_workflow_names()
        if workflows:
            classification = await classifier.classify(data.text, agents=agents, workflows=workflows)
        else:
            classification = await classifier.classify(data.text, agents=agents)
        manager = self._manager()
        _ = await manager.emit("classification", classification, source=self.name)
        workflow = classification.workflow
        voice = self._resolve_voice(classification.voice)
        if workflow is None and classification.project_state is ProjectState.NEW and self._is_new_project_request(data.text):
            workflow = self._find_workflow("project-initiation", workflows)
            voice = voice or self._resolve_voice("jane")
        match classification.category:
            case Classification.EXECUTE:
                if self._skip_existing_project_workflow(classification):
                    return
                if workflow is not None and voice is not None:
                    _ = await manager.emit(
                        "workflow_run",
                        WorkflowRunData(
                            workflow=workflow,
                            voice=voice,
                            context={"project_state": classification.project_state.value},
                        ),
                        source=self.name,
                        target="workflow_engine",
                    )
                else:
                    _ = await manager.emit(
                        "generate",
                        GenerateData(prompt=classification.text),
                        source=self.name,
                        target=voice,
                    )
            case Classification.IGNORE_SELF_TALK | Classification.IGNORE_THIRD_PARTY:
                return
            case unreachable:
                assert_never(unreachable)

    def _collect_agent_names(self) -> tuple[str, ...]:
        manager = self.manager
        if manager is None:
            return ()
        from kateto.voices.base import VoiceProfile

        names: list[str] = []
        for plugin in manager.get_plugins():
            if "voice" not in plugin.capabilities or not plugin.enabled:
                continue
            profile = getattr(plugin, "profile", None)
            names.append(profile.display_name if isinstance(profile, VoiceProfile) else plugin.name)
        return tuple(names)

    def _collect_workflow_names(self) -> tuple[str, ...]:
        manager = self.manager
        if manager is None:
            return ()
        names: set[str] = set()
        for plugin in manager.get_plugins():
            if isinstance(plugin, WorkflowEngine):
                for voice in self._collect_agent_names():
                    names.update(workflow.name for workflow in plugin.catalog.discover(voice=voice))
        return tuple(sorted(names, key=str.casefold))

    def _resolve_voice(self, selected: str | None) -> str | None:
        if selected is None:
            return None
        manager = self.manager
        if manager is None:
            return None
        normalized = selected.casefold()
        for plugin in manager.get_plugins():
            if "voice" in plugin.capabilities and plugin.enabled:
                from kateto.voices.base import VoiceProfile

                profile = getattr(plugin, "profile", None)
                display_name = profile.display_name if isinstance(profile, VoiceProfile) else plugin.name
                if plugin.name.casefold() == normalized or display_name.casefold() == normalized:
                    return plugin.name
        return None

    @staticmethod
    def _find_workflow(name: str, workflows: tuple[str, ...]) -> str | None:
        return next((workflow for workflow in workflows if workflow.casefold() == name.casefold()), None)

    @staticmethod
    def _is_new_project_request(text: str) -> bool:
        normalized = text.casefold()
        return any(
            phrase in normalized
            for phrase in ("new project", "start a project", "started a project", "project kickoff")
        )

    @staticmethod
    def _skip_existing_project_workflow(classification: ClassificationData) -> bool:
        if classification.project_state is not ProjectState.ALREADY_UNDERWAY:
            return False
        workflow = classification.workflow
        return workflow is not None and workflow.casefold() in {"project-initiation", "requirements-gathering"}

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = "classifier executor must be enabled before use"
            raise RuntimeError(msg)
        return manager
