from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import Callable

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, AudioOutput, GenerateData, TranscriptionData
from kateto.plugins.audio_input.base import AudioInputConfig, SileroVad
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600
PLAYBACK_CHUNK = b"\x00\x08" * 2_400  # 100 ms at 24 kHz mono s16LE


class SequencedSileroModel:
    def __init__(self, scores: list[float]) -> None:
        self._scores = list(scores)
        self._index = 0

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        score = self._scores[self._index]
        self._index = min(self._index + 1, len(self._scores) - 1)
        return score


class FixtureCapture:
    def __init__(self, callback: Callable[[bytes, int, None, None], None]) -> None:
        self._callback = callback

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def emit(self, samples: bytes) -> None:
        self._callback(samples, len(samples) // 2, None, None)


class FixtureCaptureFactory:
    def __init__(self) -> None:
        self.captures: list[FixtureCapture] = []

    def create(
        self,
        config: AudioInputConfig,
        callback: Callable[[bytes, int, None, None], None],
    ) -> FixtureCapture:
        capture = FixtureCapture(callback)
        self.captures.append(capture)
        return capture


class FakeWhisper(Plugin):
    """Counts transcribe calls; emits one transcription per audio chunk."""

    def __init__(self) -> None:
        super().__init__("audio_processor_whisper_fake")
        self.transcribes = 0

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("transcription", TranscriptionData)

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.transcribes += 1
        await self.required_manager.emit(
            "transcription",
            TranscriptionData(text=f"turn {self.transcribes}"),
            source=self.name,
        )


class FakeClassifier(Plugin):
    """Maps every transcription to a generate, like EXECUTE does."""

    def __init__(self) -> None:
        super().__init__("executor_classifier_fake")
        self.classifies = 0

    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("transcription", TranscriptionData)
        manager.register_event("generate", GenerateData)

    async def on_transcription(self, data: TranscriptionData) -> None:
        self.classifies += 1
        await self.required_manager.emit(
            "generate",
            GenerateData(prompt=data.text),
            source=self.name,
        )


class FakeVoice(Plugin):
    def __init__(self) -> None:
        super().__init__("fake_voice")
        self.generates = 0

    async def initialize(self) -> None:
        self.required_manager.register_event("generate", GenerateData)

    async def on_generate(self, data: GenerateData) -> None:
        del data
        self.generates += 1


async def make_chain(
    *,
    turn_silence_timeout: float,
    silence_timeout: float = 0.1,
    vad_scores: list[float],
) -> tuple[PluginManager, FixtureCapture, FakeWhisper, FakeClassifier, FakeVoice, MicrophoneAudioInput]:
    manager = PluginManager()
    whisper = FakeWhisper()
    classifier = FakeClassifier()
    voice = FakeVoice()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(
        PluginSettings(
            device="fixture",
            sample_rate=16_000,
            silence_timeout=silence_timeout,
            vad_model="silero",
            interrupt_on_vad=True,
            turn_silence_timeout=turn_silence_timeout,
        ),
        vad=SileroVad(SequencedSileroModel(vad_scores), threshold=0.5),
        capture_factory=factory,
    )
    await manager.enable_plugin(whisper)
    await manager.enable_plugin(classifier)
    await manager.enable_plugin(voice)
    await manager.enable_plugin(microphone)
    return manager, factory.captures[0], whisper, classifier, voice, microphone


def emit_segment(capture: FixtureCapture) -> None:
    capture.emit(SPEECH_FRAME)
    capture.emit(SILENCE_FRAME)


async def wait_for_count(getter: Callable[[], int], target: int, *, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while getter() < target:
            await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_three_segments_within_turn_window_produce_single_transcribe_and_generate() -> None:
    # Given: listener -> whisper (fake) -> classifier (fake) -> generate (fake).
    manager, capture, whisper, classifier, voice, _ = await make_chain(
        turn_silence_timeout=0.4,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1],
    )
    try:
        # When: 3 segments arrive closer together than turn_silence_timeout.
        for _ in range(3):
            emit_segment(capture)
            await asyncio.sleep(0.05)
        await wait_for_count(lambda: voice.generates, 1)
        await asyncio.sleep(0.6)

        # Then: one Whisper pass and one generation for the whole turn.
        assert whisper.transcribes == 1
        assert classifier.classifies == 1
        assert voice.generates == 1
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_two_turns_separated_by_silence_produce_two_each() -> None:
    # Given: the same chain with a short turn window.
    manager, capture, whisper, classifier, voice, _ = await make_chain(
        turn_silence_timeout=0.3,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.1, 0.1],
    )
    try:
        # When: 2 segments arrive farther apart than turn_silence_timeout.
        emit_segment(capture)
        await wait_for_count(lambda: voice.generates, 1)
        await asyncio.sleep(0.5)
        emit_segment(capture)
        await wait_for_count(lambda: voice.generates, 2)
        await manager.wait_for_idle()

        # Then: each turn gets its own Whisper pass and generation.
        assert whisper.transcribes == 2
        assert classifier.classifies == 2
        assert voice.generates == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_playback_bleed_produces_zero_transcribes() -> None:
    # Given: the chain while our own voice is playing (no final sentinel).
    manager, capture, whisper, classifier, voice, microphone = await make_chain(
        turn_silence_timeout=0.3,
        vad_scores=[0.9, 0.1, 0.1, 0.1, 0.1],
    )
    try:
        await microphone.on_audio_output(
            AudioOutput(
                samples=PLAYBACK_CHUNK,
                sample_rate=24_000,
                channels=1,
                format="pcm_s16le",
                final=False,
            )
        )

        # When: a full bleed segment is captured past the turn window.
        emit_segment(capture)
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.6)
        await manager.wait_for_idle()

        # Then: nothing reaches Whisper or the voices.
        assert whisper.transcribes == 0
        assert classifier.classifies == 0
        assert voice.generates == 0
    finally:
        await manager.close()
