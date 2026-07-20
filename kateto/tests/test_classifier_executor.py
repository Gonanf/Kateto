from __future__ import annotations

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import Classification, ClassificationData, GenerateData, TranscriptionData
from kateto.plugins.executor import ClassifierExecutor


class FixtureClassifier:
    def __init__(self, category: Classification) -> None:
        self._category = category

    async def classify(self, text: str, *, agents: tuple[str, ...] = ()) -> ClassificationData:
        return ClassificationData(text=text, category=self._category)


class _TestableClassifierExecutor(ClassifierExecutor):
    """Test helper that injects a fixture classifier instead of the real one."""

    def __init__(self, fixture: FixtureClassifier) -> None:
        super().__init__(settings=PluginSettings())
        self._fixture = fixture

    async def enable(self) -> None:
        self._classifier = self._fixture  # type: ignore[assignment]

    async def disable(self) -> None:
        self._classifier = None


class DynamicVoicePlugin(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.prompts: list[str | None] = []

    async def on_generate(self, data: GenerateData) -> None:
        self.prompts.append(data.prompt)


@pytest.mark.asyncio
async def test_execute_broadcasts_to_dynamically_named_voice_plugins() -> None:
    # Given: subscribers whose names are not known by the classifier executor.
    manager = PluginManager()
    await manager.enable_plugin(_TestableClassifierExecutor(FixtureClassifier(Classification.EXECUTE)))
    voices = (DynamicVoicePlugin("voice_orchid"), DynamicVoicePlugin("voice_sable"))
    for voice in voices:
        await manager.enable_plugin(voice)

    try:
        # When: a transcription is classified as executable.
        await manager.emit("transcription", TranscriptionData(text="open the calendar"), source="fixture")
        await manager.wait_for_idle()

        # Then: one generic, untargeted generate reaches every interested subscriber.
        generate_events = [event for event in manager.get_events() if event.name == "generate"]
        assert [(event.target, event.data) for event in generate_events] == [
            (None, GenerateData(prompt="open the calendar")),
        ]
        assert [voice.prompts for voice in voices] == [["open the calendar"], ["open the calendar"]]
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", (Classification.IGNORE_SELF_TALK, Classification.IGNORE_THIRD_PARTY))
async def test_ignore_classification_does_not_generate(category: Classification) -> None:
    # Given: dynamically named subscribers and a classifier that ignores the transcription.
    manager = PluginManager()
    await manager.enable_plugin(_TestableClassifierExecutor(FixtureClassifier(category)))
    voice = DynamicVoicePlugin("voice_unlisted")
    await manager.enable_plugin(voice)

    try:
        # When: a transcription is classified as ignored speech.
        await manager.emit("transcription", TranscriptionData(text="not addressed to the system"), source="fixture")
        await manager.wait_for_idle()

        # Then: classification is preserved, but no generate event reaches the subscriber.
        assert [event.name for event in manager.get_events()] == ["transcription", "classification"]
        assert voice.prompts == []
    finally:
        await manager.close()
