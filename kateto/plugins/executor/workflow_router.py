from __future__ import annotations

from typing import Protocol, override

from kateto.core.config import PluginSettings
from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    ProjectState,
    WorkflowRunData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow_engine import WorkflowEngine
from kateto.providers import ClassifierProvider, WorkflowCandidate, WorkflowSelection

class WorkflowSelector(Protocol):
    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None: ...

    async def aclose(self) -> None: ...


class WorkflowRouter(Plugin):
    """Select and start an available workflow from classification events."""

    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("executor_workflow_router", capabilities=("workflow-router",))
        self._settings: PluginSettings = settings
        self._provider: WorkflowSelector | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("classification", ClassificationData)
        manager.register_event("workflow_run", WorkflowRunData)
        manager.register_event("generate", GenerateData)

    @override
    async def enable(self) -> None:
        provider = ClassifierProvider(self._settings)
        self._provider = await provider.__aenter__()

    @override
    async def disable(self) -> None:
        provider = self._provider
        self._provider = None
        if provider is not None:
            await provider.aclose()

    async def on_classification(self, data: ClassificationData) -> None:
        if data.category is not Classification.EXECUTE:
            return
        provider = self._provider
        if provider is None:
            raise RuntimeError("workflow router must be enabled before use")
        candidates = self._workflow_candidates()
        selection = self._new_project_selection(data, candidates)
        if selection is None and candidates:
            selection = await provider.select_workflow(data.text, candidates=candidates)
        selected = self._resolve_selection(selection, candidates)
        if selected is not None and not self._is_inapplicable_for_existing_project(selected.name, data.project_state):
            context: dict[str, str | int | float | bool | None] = {
                "project_state": data.project_state.value,
            }
            if selection is not None:
                context["confidence"] = selection.confidence
            _ = await self._manager().emit(
                "workflow_run",
                WorkflowRunData(workflow=selected.name, voice=selected.voice, context=context),
                source=self.name,
                target="workflow_engine",
            )
            return
        _ = await self._manager().emit(
            "generate",
            GenerateData(prompt=data.text),
            source=self.name,
            target=self._resolve_voice(data.voice),
        )

    def _workflow_candidates(self) -> tuple[WorkflowCandidate, ...]:
        manager = self._manager()
        engine = next(
            (plugin for plugin in manager.get_plugins() if isinstance(plugin, WorkflowEngine)),
            None,
        )
        if engine is None:
            return ()
        candidates: list[WorkflowCandidate] = []
        for plugin in manager.get_plugins():
            if not plugin.enabled or "voice" not in plugin.capabilities:
                continue
            for definition in engine.catalog.discover(voice=plugin.name):
                candidates.append(
                    WorkflowCandidate(
                        name=definition.name,
                        voice=plugin.name,
                        description=definition.description,
                    ),
                )
        return tuple(sorted(candidates, key=lambda candidate: (candidate.name.casefold(), candidate.voice.casefold())))

    @staticmethod
    def _resolve_selection(
        selection: WorkflowSelection | None,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowCandidate | None:
        if selection is None:
            return None
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.name.casefold() == selection.name.casefold()
                and candidate.voice.casefold() == selection.voice.casefold()
            ),
            None,
        )

    @staticmethod
    def _is_inapplicable_for_existing_project(workflow: str, state: ProjectState) -> bool:
        return state is ProjectState.ALREADY_UNDERWAY and workflow.casefold() in {
            "project-initiation",
            "requirements-gathering",
        }

    @staticmethod
    def _new_project_selection(
        data: ClassificationData,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        if data.project_state is not ProjectState.NEW:
            return None
        normalized = data.text.casefold()
        if not any(
            phrase in normalized
            for phrase in (
                "new project",
                "nuevo proyecto",
                "start a project",
                "started a project",
                "project kickoff",
            )
        ):
            return None
        candidate = next(
            (item for item in candidates if item.name.casefold() == "project-initiation"),
            None,
        )
        if candidate is None:
            return None
        return WorkflowSelection(name=candidate.name, voice=candidate.voice, confidence=1.0)

    def _resolve_voice(self, selected: str | None) -> str | None:
        if selected is None:
            return None
        normalized = selected.casefold()
        return next(
            (
                plugin.name
                for plugin in self._manager().get_plugins()
                if plugin.enabled
                and "voice" in plugin.capabilities
                and plugin.name.casefold() == normalized
            ),
            None,
        )

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            raise RuntimeError("workflow router must be attached to a manager")
        return manager
