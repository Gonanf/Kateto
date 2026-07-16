from __future__ import annotations

from typing import Protocol, assert_never, override

from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    TranscriptionData,
)
from kateto.core.plugin import Plugin, PluginManagerProtocol


class IntentClassifier(Protocol):
    async def classify(self, text: str) -> ClassificationData: ...


class ClassifierExecutor(Plugin):
    def __init__(self, *, classifier: IntentClassifier) -> None:
        super().__init__("executor_classifier", receive_self_events=True)
        self._classifier: IntentClassifier = classifier

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("classification", ClassificationData)
        manager.register_event("generate", GenerateData)

    async def on_transcription(self, data: TranscriptionData) -> None:
        classification = await self._classifier.classify(data.text)
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

    def _manager(self) -> PluginManagerProtocol:
        manager = self.manager
        if manager is None:
            msg = "classifier executor must be enabled before use"
            raise RuntimeError(msg)
        return manager
