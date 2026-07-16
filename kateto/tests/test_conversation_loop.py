from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.event import AudioData, Classification, GenerateData, TextChunk, TodoItemData
from kateto.plugins.audio_processor import WhisperAudioProcessor
from kateto.plugins.executor import ClassifierExecutor, InterruptExecutor, TodoListExecutor
from kateto.tests.conversation_support import (
    BlockingAudioOutput,
    BlockingFixtureProvider,
    FixtureClassifier,
    FixtureTranscriber,
    StreamingFixtureProvider,
    enable_voices,
    write_references,
)


async def _enable_pipeline(
    manager: PluginManager,
    *,
    config_dir: Path,
    transcriber: FixtureTranscriber,
    classifier: FixtureClassifier,
    provider: StreamingFixtureProvider | BlockingFixtureProvider,
) -> None:
    await manager.enable_plugin(InterruptExecutor())
    await manager.enable_plugin(WhisperAudioProcessor(provider=transcriber))
    await manager.enable_plugin(ClassifierExecutor(classifier=classifier))
    await manager.enable_plugin(TodoListExecutor(config_dir=config_dir, voice="doktor"))
    await enable_voices(manager, config_dir=config_dir, provider=provider)


@pytest.mark.asyncio
async def test_audio_to_execute_emits_ordered_transcript_classification_and_three_targeted_generates(tmp_path: Path) -> None:
    # Given: the real event bus with active P0 voices and a fixture inference boundary.
    write_references(tmp_path)
    manager = PluginManager()
    transcriber = FixtureTranscriber(("plan tomorrow standup",))
    classifier = FixtureClassifier(Classification.EXECUTE)
    await _enable_pipeline(
        manager,
        config_dir=tmp_path,
        transcriber=transcriber,
        classifier=classifier,
        provider=StreamingFixtureProvider(),
    )
    try:
        # When: an audio segment enters the conversation loop.
        await manager.emit("audio_chunk", AudioData(samples=b"\x01\x00", format="pcm_s16le"), source="fixture")
        await manager.wait_for_idle()

        # Then: its visible event prefix is stable and every active P0 voice gets its own trigger.
        events = manager.get_events()
        assert [event.name for event in events[:3]] == ["audio_chunk", "transcription", "classification"]
        generate_events = [event for event in events if event.name == "generate"]
        assert [
            (event.source, event.target, event.data.prompt)
            for event in generate_events
            if isinstance(event.data, GenerateData)
        ] == [
            ("executor_classifier", "jane", "plan tomorrow standup"),
            ("executor_classifier", "doktor", "plan tomorrow standup"),
            ("executor_classifier", "conquest", "plan tomorrow standup"),
        ]
        assert transcriber.received[0].format == "pcm_s16le"
        assert classifier.received == ["plan tomorrow standup"]
        assert [event.data.voice_id for event in events if event.name == "text_chunk" and isinstance(event.data, TextChunk)] == [
            "doktor",
            "conquest",
        ]
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("category", (Classification.IGNORE_SELF_TALK, Classification.IGNORE_THIRD_PARTY))
async def test_ignored_classifications_end_after_the_classification_event(category: Classification, tmp_path: Path) -> None:
    # Given: a loop whose classifier labels the utterance as non-addressed speech.
    write_references(tmp_path)
    manager = PluginManager()
    await _enable_pipeline(
        manager,
        config_dir=tmp_path,
        transcriber=FixtureTranscriber(("I am thinking aloud",)),
        classifier=FixtureClassifier(category),
        provider=StreamingFixtureProvider(),
    )
    try:
        # When: the utterance is transcribed and classified.
        await manager.emit("audio_chunk", AudioData(samples=b"\x01\x00", format="pcm_s16le"), source="fixture")
        await manager.wait_for_idle()

        # Then: neither ignored category can wake a voice or mutate the TODO surface.
        assert [event.name for event in manager.get_events()] == ["audio_chunk", "transcription", "classification"]
        assert not (tmp_path / "voices" / "doktor" / "TODO.md").exists()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_todo_creation_update_and_completion_emit_a_backlog_sync_boundary(tmp_path: Path) -> None:
    # Given: two executable utterances that create then complete the same planned work.
    write_references(tmp_path)
    manager = PluginManager()
    await _enable_pipeline(
        manager,
        config_dir=tmp_path,
        transcriber=FixtureTranscriber(("plan tomorrow standup", "complete tomorrow standup", "complete tomorrow standup")),
        classifier=FixtureClassifier(Classification.EXECUTE),
        provider=StreamingFixtureProvider(),
    )
    try:
        # When: each utterance travels through the same audio entrypoint.
        for _ in range(3):
            await manager.emit("audio_chunk", AudioData(samples=b"\x01\x00", format="pcm_s16le"), source="fixture")
            await manager.wait_for_idle()

        # Then: the durable list is idempotent and one typed completion event is available for backlog sync.
        todo_path = tmp_path / "voices" / "doktor" / "TODO.md"
        assert todo_path.read_text(encoding="utf-8") == "# TODO\n\n- [x] tomorrow standup\n"
        completions = [event.data for event in manager.get_events() if event.name == "todo_completed"]
        assert completions == [TodoItemData(voice="doktor", task="tomorrow standup", completed=True)]
        assert not [event for event in manager.get_events() if event.name.startswith("backlog_")]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_interrupt_cancels_active_llm_and_tts_then_the_next_audio_segment_resumes(tmp_path: Path) -> None:
    # Given: an active Doktor stream plus a separately active TTS task.
    write_references(tmp_path)
    manager = PluginManager()
    provider = BlockingFixtureProvider()
    await _enable_pipeline(
        manager,
        config_dir=tmp_path,
        transcriber=FixtureTranscriber(("calendar BLOCK", "calendar resume")),
        classifier=FixtureClassifier(Classification.EXECUTE),
        provider=provider,
    )
    audio_output = BlockingAudioOutput()
    await manager.enable_plugin(audio_output)
    try:
        await manager.emit("audio_chunk", AudioData(samples=b"\x01\x00", format="pcm_s16le"), source="fixture")
        await asyncio.wait_for(provider.blocked.wait(), timeout=1)
        await asyncio.wait_for(audio_output.started.wait(), timeout=1)

        # When: voice activity interrupts the active stream, then a new segment arrives.
        await manager.interrupt(reason="voice_activity", source="fixture")
        await asyncio.wait_for(provider.cancelled.wait(), timeout=1)
        await asyncio.wait_for(audio_output.cancelled.wait(), timeout=1)
        await manager.wait_for_idle()
        await manager.emit("audio_chunk", AudioData(samples=b"\x01\x00", format="pcm_s16le"), source="fixture")
        await manager.wait_for_idle()

        # Then: cancellation is observable and a fresh utterance reaches a resumed stream.
        names = [event.name for event in manager.get_events()]
        assert names.count("conversation_interrupted") == 1
        assert names.count("conversation_resumed") == 1
        assert provider.calls == 2
        assert [event.data.text for event in manager.get_events() if event.name == "text_chunk" and isinstance(event.data, TextChunk)][-1] == "resumed"
    finally:
        await manager.close()
