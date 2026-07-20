from __future__ import annotations

from typing import TYPE_CHECKING, assert_never, override

from kateto.core.config import PluginSettings
from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    TranscriptionData,
)
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager

if TYPE_CHECKING:
    from kateto.providers import ClassifierProvider


class ClassifierExecutor(Plugin):
    def __init__(self, settings: PluginSettings) -> None:
        super().__init__("executor_classifier", receive_self_events=True)
        self._settings: PluginSettings = settings
        self._classifier: ClassifierProvider | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("classification", ClassificationData)
        manager.register_event("generate", GenerateData)

    @override
    async def enable(self) -> None:
        from kateto.providers import ClassifierProvider

        self._classifier = ClassifierProvider(self._settings)
        await self._classifier.__aenter__()

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
        classification = await classifier.classify(data.text, agents=agents)
        manager = self._manager()
        _ = await manager.emit("classification", classification, source=self.name)
        match classification.category:
            case Classification.EXECUTE:
                _ = await manager.emit(
                    "generate",
                    GenerateData(prompt=classification.text),
                    source=self.name,
                )
            case Classification.IGNORE_SELF_TALK | Classification.IGNORE_THIRD_PARTY:
                return
            case unreachable:
                assert_never(unreachable)

    def _collect_agent_names(self) -> tuple[str, ...]:
        from kateto.voices.base import VoiceAgent

        manager = self.manager
        if manager is None:
            return ()
        return tuple(
            plugin.profile.display_name
            for plugin in manager.get_plugins()
            if isinstance(plugin, VoiceAgent) and plugin.enabled
        )

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = "classifier executor must be enabled before use"
            raise RuntimeError(msg)
        return manager
