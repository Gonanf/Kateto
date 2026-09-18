from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import Callable

import pytest
from loguru import logger

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData
from kateto.plugins.audio_input.base import AudioInputConfig, SileroVad
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600


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


class RecordingAudioPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("audio_recorder")
        self.chunks: list[AudioData] = []
        self.chunk_received = asyncio.Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.chunks.append(data)
        self.chunk_received.set()


class LogCapture:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._handler_id = logger.add(self._append, level="INFO")

    def _append(self, message: object) -> None:
        self.lines.append(str(message))

    def stop(self) -> None:
        logger.remove(self._handler_id)


def make_settings(
    *,
    turn_silence_timeout: float | None = None,
    max_turn_secs: float | None = None,
    turn_hold_ms: float | None = None,
    silence_timeout: float = 0.1,
) -> PluginSettings:
    return PluginSettings(
        device="fixture",
        sample_rate=16_000,
        silence_timeout=silence_timeout,
        vad_model="silero",
        interrupt_on_vad=True,
        turn_silence_timeout=turn_silence_timeout,
        max_turn_secs=max_turn_secs,
        turn_hold_ms=turn_hold_ms,
    )


def make_microphone(
    *,
    turn_silence_timeout: float | None = None,
    max_turn_secs: float | None = None,
    turn_hold_ms: float | None = None,
    silence_timeout: float = 0.1,
    vad_scores: list[float],
) -> tuple[MicrophoneAudioInput, FixtureCaptureFactory]:
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(
        make_settings(
            turn_silence_timeout=turn_silence_timeout,
            max_turn_secs=max_turn_secs,
            turn_hold_ms=turn_hold_ms,
            silence_timeout=silence_timeout,
        ),
        vad=SileroVad(SequencedSileroModel(list(vad_scores)), threshold=0.5),
        capture_factory=factory,
    )
    return microphone, factory


def test_turn_hold_ms_default_is_zero_and_configurable() -> None:
    # Given: default settings and an explicit hold override.
    defaults = AudioInputConfig.from_settings(make_settings(), source="mic", require_device=False)
    tuned = AudioInputConfig.from_settings(
        make_settings(turn_hold_ms=250.0), source="mic", require_device=False
    )

    # Then: neutral default (no extra latency) and TOML override honored.
    assert defaults.turn_hold_ms == 0.0
    assert tuned.turn_hold_ms == 250.0


@pytest.mark.asyncio
async def test_resumed_speech_cancels_pending_flush_and_merges() -> None:
    # Given: a turn window with one closed segment and its flush pending.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=0.5,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.1, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)
    capture = LogCapture()
    try:
        seg = SPEECH_FRAME + SILENCE_FRAME
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.sleep(0.2)
        # Timer (0.5s) still pending: nothing flushed yet.
        assert recorder.chunks == []

        # When: the user resumes speaking inside the turn window.
        factory.captures[0].emit(SPEECH_FRAME)
        await asyncio.sleep(0.15)
        await manager.wait_for_idle()

        # Then: the partial turn never flushed while the user was talking.
        assert recorder.chunks == []
        assert any("turn flush cancelled: user resumed speaking" in line for line in capture.lines)

        # When: the resumed utterance closes and real silence follows.
        factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.sleep(0.1)
        assert recorder.chunks == []
        await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
        await asyncio.sleep(0.7)
        await manager.wait_for_idle()

        # Then: a single emit carries both segments concatenated.
        assert len(recorder.chunks) == 1
        assert recorder.chunks[0].samples == seg + seg
        assert any("turn flush reason=silence" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_genuine_silence_flushes_single_chunk() -> None:
    # Given: one closed segment and no resumed speech.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=0.3,
        vad_scores=[0.9, 0.1, 0.1, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)
    capture = LogCapture()
    try:
        # When: the segment closes and silence outlasts the turn window.
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
        await asyncio.sleep(0.5)
        await manager.wait_for_idle()

        # Then: exactly one chunk with the silence diagnostic.
        assert len(recorder.chunks) == 1
        assert recorder.chunks[0].samples == SPEECH_FRAME + SILENCE_FRAME
        assert any("turn flush reason=silence segments=1" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_max_turn_secs_still_forces_emit_despite_resumed_speech() -> None:
    # Given: a long turn window but a tiny hard cap.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=10.0,
        max_turn_secs=0.25,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.9, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)
    try:
        # When: segments keep arriving (each resumption cancels the timer).
        for _ in range(3):
            factory.captures[0].emit(SPEECH_FRAME)
            factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
        await manager.wait_for_idle()

        # Then: the hard cap still forced the emit.
        assert len(recorder.chunks) == 1
        assert recorder.chunks[0].duration_ms >= 250.0
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_turn_hold_ms_retains_and_cancels_on_speech_within_hold() -> None:
    # Given: silence timeout expired but the extra hold still pending.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=0.2,
        turn_hold_ms=400.0,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.1, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)
    capture = LogCapture()
    try:
        seg = SPEECH_FRAME + SILENCE_FRAME
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        # Past turn_silence_timeout (0.2) but inside the hold (total 0.6).
        await asyncio.sleep(0.3)
        assert recorder.chunks == []

        # When: speech returns inside the hold.
        factory.captures[0].emit(SPEECH_FRAME)
        await asyncio.sleep(0.1)
        await manager.wait_for_idle()
        assert recorder.chunks == []
        assert any("turn flush cancelled: user resumed speaking" in line for line in capture.lines)

        # When: the resumed utterance closes and silence follows.
        factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.sleep(0.1)
        assert recorder.chunks == []
        await asyncio.wait_for(recorder.chunk_received.wait(), timeout=3)
        await asyncio.sleep(0.8)
        await manager.wait_for_idle()

        # Then: one merged emit, not a partial flush during the hold.
        assert len(recorder.chunks) == 1
        assert recorder.chunks[0].samples == seg + seg
    finally:
        capture.stop()
        await manager.close()
