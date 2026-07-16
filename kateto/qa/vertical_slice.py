from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from kateto.core import Plugin, PluginManager
from kateto.core.plugin import PluginManagerProtocol
from kateto.core.event import (
    AudioData,
    AudioOutput,
    Classification,
    ClassificationData,
    TextChunk,
    TranscriptionData,
)
from kateto.plugins.executor import ClassifierExecutor, InterruptExecutor, TodoListExecutor
from kateto.plugins.audio_processor import WhisperAudioProcessor
from kateto.tests.conversation_support import enable_voices, write_references
from kateto.voices.base import GenerationRequest, StreamingProvider


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    transcriptions: tuple[str, ...]
    classifications: tuple[Classification, ...]
    generate_targets: tuple[str, ...]
    text_chunks: int
    audio_chunks: int
    todo_text: str | None
    interrupts: int
    resumes: int
    cancelled_streams: int
    manager_alive: bool


class _FixtureTranscriber:
    def __init__(self, prompts: tuple[str, ...]) -> None:
        self._prompts = iter(prompts)

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        return TranscriptionData(text=next(self._prompts))


class _FixtureClassifier:
    async def classify(self, text: str) -> ClassificationData:
        category = (
            Classification.IGNORE_SELF_TALK
            if text.casefold() == "i am thinking aloud"
            else Classification.EXECUTE
        )
        return ClassificationData(text=text, category=category)


class _FixtureProvider(StreamingProvider):
    def __init__(self, interrupted: bool) -> None:
        self._interrupted = interrupted
        self.tokens_seen = 0
        self.token_event = asyncio.Event()
        self.cancelled_streams = 0
        self._resume_ready = False
        self._release = asyncio.Event()

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[str]:
        if self._interrupted and not self._resume_ready:
            for token in ("one", " two", " three"):
                self.tokens_seen += 1
                if self.tokens_seen >= 3:
                    self.token_event.set()
                yield token
            try:
                await self._release.wait()
            except asyncio.CancelledError:
                self.cancelled_streams += 1
                self._resume_ready = True
                raise
            return
        yield "resumed" if self._interrupted else "fixture response"


class _FixtureAudioOutput(Plugin):
    def __init__(self) -> None:
        super().__init__("fixture_audio_output")

    async def initialize(self) -> None:
        self._manager().register_event("text_chunk", TextChunk)
        self._manager().register_event("audio_output", AudioOutput)

    async def on_text_chunk(self, data: TextChunk) -> None:
        await self._manager().emit(
            "audio_output",
            AudioOutput(
                samples=b"fixture-pcm",
                sample_rate=16_000,
                channels=1,
                format="pcm_s16le",
                voice_id=data.voice_id,
                sequence=data.sequence,
                final=data.final,
            ),
            source=self.name,
        )

    def _manager(self) -> PluginManagerProtocol:
        manager = self.manager
        if manager is None:
            raise RuntimeError("fixture audio output must be enabled before use")
        return manager


async def run_fixture(prompt: str, interrupt_at: int | None = None) -> VerticalSliceResult:
    if interrupt_at is not None and interrupt_at < 1:
        raise ValueError("interrupt_at must be positive")
    with TemporaryDirectory(prefix="kateto-vertical-slice-") as directory:
        config_dir = Path(directory)
        write_references(config_dir)
        manager = PluginManager()
        provider = _FixtureProvider(interrupt_at is not None)
        transcriber = _FixtureTranscriber((prompt, prompt) if interrupt_at is not None else (prompt,))
        classifier = _FixtureClassifier()
        await manager.enable_plugin(InterruptExecutor())
        await manager.enable_plugin(WhisperAudioProcessor(provider=transcriber))
        await manager.enable_plugin(ClassifierExecutor(classifier=classifier))
        await manager.enable_plugin(TodoListExecutor(config_dir=config_dir, voice="doktor"))
        await enable_voices(manager, config_dir=config_dir, provider=provider)
        audio_output = _FixtureAudioOutput()
        await manager.enable_plugin(audio_output)
        try:
            await manager.emit(
                "audio_chunk",
                AudioData(samples=b"\x01\x00", format="pcm_s16le", source="fixture"),
                source="fixture",
            )
            if interrupt_at is not None:
                await asyncio.wait_for(provider.token_event.wait(), timeout=1)
                await manager.interrupt(reason="voice_activity", source="fixture")
                await manager.wait_for_idle()
                await manager.emit(
                    "audio_chunk",
                    AudioData(samples=b"\x01\x00", format="pcm_s16le", source="fixture"),
                    source="fixture",
                )
            await manager.wait_for_idle()
            events = manager.get_events()
            todo_path = config_dir / "voices" / "doktor" / "TODO.md"
            return VerticalSliceResult(
                transcriptions=tuple(
                    data.text
                    for event in events
                    if event.name == "transcription" and isinstance(data := event.data, TranscriptionData)
                ),
                classifications=tuple(
                    data.category
                    for event in events
                    if event.name == "classification" and isinstance(data := event.data, ClassificationData)
                ),
                generate_targets=tuple(event.target for event in events if event.name == "generate" if event.target is not None),
                text_chunks=sum(event.name == "text_chunk" for event in events),
                audio_chunks=sum(event.name == "audio_output" for event in events),
                todo_text=todo_path.read_text(encoding="utf-8") if todo_path.is_file() else None,
                interrupts=sum(event.name == "conversation_interrupted" for event in events),
                resumes=sum(event.name == "conversation_resumed" for event in events),
                cancelled_streams=provider.cancelled_streams,
                manager_alive=all(plugin.enabled for plugin in manager.get_plugins()),
            )
        finally:
            await manager.close()


def _parse_interrupt(value: str) -> int:
    prefix, separator, token = value.partition(":")
    if prefix != "token" or not separator:
        raise argparse.ArgumentTypeError("expected token:N")
    try:
        return int(token)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected token:N") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="store_true", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--interrupt-at", type=_parse_interrupt)
    args = parser.parse_args()
    result = asyncio.run(run_fixture(args.prompt, args.interrupt_at))
    for transcription in result.transcriptions:
        print(f"TRANSCRIPTION text={transcription}")
    for classification in result.classifications:
        print(f"CLASSIFICATION category={classification.value}")
    for target in result.generate_targets:
        print(f"GENERATE target={target}")
    print(f"STREAMED_RESPONSE chunks={result.text_chunks}")
    print(f"AUDIO_CHUNK count={result.audio_chunks}")
    print("TTS_PCM format=pcm_s16le")
    if result.interrupts:
        print(f"INTERRUPT cancellation_streams={result.cancelled_streams}")
        print(f"RESUME count={result.resumes}")
    print(f"TRACE manager_alive={'true' if result.manager_alive else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
