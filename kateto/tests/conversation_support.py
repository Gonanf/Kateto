from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from kateto.core import Plugin, PluginManager
from kateto.core.event import AudioData, Classification, ClassificationData, InterruptData, TextChunk, TranscriptionData
from kateto.voices.base import GenerationRequest, StreamingProvider
from kateto.voices.conquest import Conquest
from kateto.voices.doktor import Doktor
from kateto.voices.jane import Jane


class FixtureTranscriber:
    def __init__(self, texts: Sequence[str]) -> None:
        self._texts = iter(texts)
        self.received: list[AudioData] = []

    async def __aenter__(self) -> FixtureTranscriber:
        return self

    async def aclose(self) -> None:
        pass

    async def transcribe(self, audio: AudioData) -> TranscriptionData:
        self.received.append(audio)
        return TranscriptionData(text=next(self._texts))


class FixtureClassifier:
    def __init__(self, category: Classification) -> None:
        self._category = category
        self.received: list[str] = []

    async def __aenter__(self) -> FixtureClassifier:
        return self

    async def aclose(self) -> None:
        pass

    async def classify(self, text: str) -> ClassificationData:
        self.received.append(text)
        return ClassificationData(text=text, category=self._category)


class StreamingFixtureProvider:
    def __init__(self, tokens: tuple[str, ...] = ("fixture response",)) -> None:
        self._tokens = tokens
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._stream_tokens()

    async def _stream_tokens(self) -> AsyncIterator[str]:
        for token in self._tokens:
            yield token


class BlockingFixtureProvider:
    def __init__(self) -> None:
        self.blocked = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = 0

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        return self._stream_tokens()

    async def _stream_tokens(self) -> AsyncIterator[str]:
        self.calls += 1
        match self.calls:
            case 1:
                yield "one"
                yield " two"
                yield " three"
                self.blocked.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            case 2:
                yield "resumed"
            case unexpected:
                raise AssertionError(f"unexpected provider call {unexpected}")


class BlockingAudioOutput(Plugin):
    def __init__(self) -> None:
        super().__init__("fixture_tts")
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def on_text_chunk(self, data: TextChunk) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._play(), name="fixture-tts")
            self.started.set()

    async def on_interrupt(self, data: InterruptData) -> None:
        await self._cancel()

    async def _cancel(self) -> None:
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                self.cancelled.set()

    async def disable(self) -> None:
        await self._cancel()

    async def _play(self) -> None:
        await asyncio.Event().wait()


def write_references(config_dir: Path) -> None:
    for voice in ("jane", "doktor", "conquest"):
        reference = config_dir / "voices" / voice / "reference.wav"
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_bytes(b"RIFFfixtureWAVE")


async def enable_voices(
    manager: PluginManager,
    *,
    config_dir: Path,
    provider: StreamingProvider,
) -> tuple[Jane, Doktor, Conquest]:
    voices = (
        Jane(config_dir=config_dir, provider=provider),
        Doktor(config_dir=config_dir, provider=provider),
        Conquest(config_dir=config_dir, provider=provider),
    )
    for voice in voices:
        await manager.enable_plugin(voice)
    return voices
