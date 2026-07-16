from __future__ import annotations

from typing import Final, Protocol, assert_never

from kateto.core.event import (
    Classification,
    ClassificationData,
    GenerateData,
    TranscriptionData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin, PluginManagerProtocol


_P0_VOICE_NAMES: Final[tuple[str, ...]] = ("jane", "doktor", "conquest")


class IntentClassifier(Protocol):
    async def classify(self, text: str) -> ClassificationData: ...


class ClassifierExecutor(Plugin):
    def __init__(self, *, classifier: IntentClassifier) -> None:
        super().__init__("executor_classifier", receive_self_events=True)
        self._classifier = classifier

    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("classification", ClassificationData)
        manager.register_event("generate", GenerateData)

    async def on_transcription(self, data: TranscriptionData) -> None:
        classification = await self._classifier.classify(data.text)
        manager = self._manager()
        await manager.emit("classification", classification, source=self.name)
        match classification.category:
            case Classification.EXECUTE:
                active_plugins = {plugin.name for plugin in manager.get_plugins() if plugin.enabled}
                for voice_name in _P0_VOICE_NAMES:
                    if voice_name in active_plugins:
                        await manager.emit(
                            "generate",
                            GenerateData(prompt=classification.text),
                            source=self.name,
                            target=voice_name,
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
