from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import Callable
from time import monotonic

import pytest
from loguru import logger

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, AudioOutput, InterruptData
from kateto.plugins.audio_input.base import AudioInputConfig, SileroVad
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600
LOUD_FRAME = b"\xff\x7f" * 1_600  # 100 ms near full-scale: loud user voice
# Moderate playback level (~0.06 raw RMS): audible bleed, well below a shout.
PLAYBACK_CHUNK = b"\x00\x08" * 2_400  # 100 ms at 24 kHz mono s16LE


class SequencedSileroModel:
    """Deterministic model: pops scores, repeating the last one when exhausted."""

    def __init__(self, scores: list[float], *, cycle_last: bool = False) -> None:
        self._scores = list(scores)
        self._cycle_last = cycle_last
        self._index = 0

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        if self._cycle_last:
            return self._scores[-1]
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


class InterruptRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__("interrupt_recorder")
        self.interrupts: list[InterruptData] = []
        self.received = asyncio.Event()

    async def on_interrupt(self, data: InterruptData) -> None:
        self.interrupts.append(data)
        self.received.set()


def make_vad(scores: list[float], *, cycle_last: bool = False) -> SileroVad:
    return SileroVad(SequencedSileroModel(scores, cycle_last=cycle_last), threshold=0.5)


def make_settings(
    *,
    interrupt_on_vad: bool = True,
    barge_in_grace_ms: float | None = None,
    barge_in_level_factor: float | None = None,
    barge_in_min_speech_ms: float | None = None,
    turn_silence_timeout: float | None = None,
    max_turn_secs: float | None = None,
    silence_timeout: float = 0.2,
) -> PluginSettings:
    return PluginSettings(
        device="fixture",
        sample_rate=16_000,
        silence_timeout=silence_timeout,
        vad_model="silero",
        interrupt_on_vad=interrupt_on_vad,
        barge_in_grace_ms=barge_in_grace_ms,
        barge_in_level_factor=barge_in_level_factor,
        barge_in_min_speech_ms=barge_in_min_speech_ms,
        turn_silence_timeout=turn_silence_timeout,
        max_turn_secs=max_turn_secs,
    )


def make_microphone(
    *,
    interrupt_on_vad: bool = True,
    barge_in_grace_ms: float | None = None,
    barge_in_level_factor: float | None = None,
    barge_in_min_speech_ms: float | None = None,
    turn_silence_timeout: float | None = None,
    max_turn_secs: float | None = None,
    silence_timeout: float = 0.2,
    vad_scores: list[float] = (0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.9, 0.1, 0.1),
    cycle_last: bool = False,
) -> tuple[MicrophoneAudioInput, FixtureCaptureFactory]:
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(
        make_settings(
            interrupt_on_vad=interrupt_on_vad,
            barge_in_grace_ms=barge_in_grace_ms,
            barge_in_level_factor=barge_in_level_factor,
            barge_in_min_speech_ms=barge_in_min_speech_ms,
            turn_silence_timeout=turn_silence_timeout,
            max_turn_secs=max_turn_secs,
            silence_timeout=silence_timeout,
        ),
        vad=make_vad(list(vad_scores), cycle_last=cycle_last),
        capture_factory=factory,
    )
    return microphone, factory


class LogCapture:
    """Collect loguru records emitted during a test."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._handler_id = logger.add(self._append, level="INFO")

    def _append(self, message: object) -> None:
        self.lines.append(str(message))

    def stop(self) -> None:
        logger.remove(self._handler_id)


@pytest.mark.asyncio
async def test_vad_during_grace_of_own_playback_does_not_interrupt() -> None:
    # Given: the listener is playing its own voice through the speakers.
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone()
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    capture = LogCapture()
    try:
        # When: the mic picks up speech right after playback started (self-bleed).
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        await manager.wait_for_idle()

        # Then: no interrupt is emitted and the reason is logged.
        assert interrupts.interrupts == []
        assert any("vad ignored: own playback within grace" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_sustained_speech_beyond_grace_interrupts_playback() -> None:
    # Given: own playback active with a short grace window and speech that keeps
    # going (a real user talking over the response).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(
        barge_in_grace_ms=200.0, vad_scores=[0.9], cycle_last=True
    )
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)

    # When: speech frames keep arriving while wall-clock time passes the grace.
    capture = factory.captures[0]
    deadline = monotonic() + 5.0
    while not interrupts.received.is_set():
        capture.emit(SPEECH_FRAME)
        await asyncio.sleep(0.05)
        assert monotonic() < deadline, "barge-in never fired past the grace window"

    # Then: exactly one interrupt is emitted for the sustained speech.
    await manager.wait_for_idle()
    assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
    await manager.close()


@pytest.mark.asyncio
async def test_vad_without_own_playback_interrupts_immediately() -> None:
    # Given: no playback is active (nobody is speaking through the speakers).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone()
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)

    # When: the VAD detects speech.
    factory.captures[0].emit(SPEECH_FRAME)
    await asyncio.wait_for(interrupts.received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: the interrupt fires exactly as before the grace gating existed.
    assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("playback_active", [True, False])
async def test_interrupt_on_vad_false_never_interrupts(playback_active: bool) -> None:
    # Given: interrupt_on_vad disabled (the documented workaround config).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(interrupt_on_vad=False)
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    if playback_active:
        microphone.set_playback_active(True)
        # Fast-forward past any grace so only the flag governs the decision.
        microphone._playback_started_at = monotonic() - 60.0

    # When: the mic picks up sustained speech.
    for _ in range(4):
        factory.captures[0].emit(SPEECH_FRAME)
        await asyncio.sleep(0.02)
    await manager.wait_for_idle()

    # Then: no interrupt is emitted either way.
    assert interrupts.interrupts == []
    await manager.close()


@pytest.mark.asyncio
async def test_clearing_playback_flag_reopens_barge_in_after_grace() -> None:
    # Given: speech was deferred during own playback, then playback finished.
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(vad_scores=[0.9, 0.1, 0.1, 0.9, 0.1, 0.1])
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await manager.wait_for_idle()
    assert interrupts.interrupts == []

    # When: the playback flag is cleared and new speech arrives.
    microphone.set_playback_active(False)
    factory.captures[0].emit(SPEECH_FRAME)
    await asyncio.wait_for(interrupts.received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: VAD interrupts normally again — the grace never leaves the system deaf.
    assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
    await manager.close()


@pytest.mark.asyncio
async def test_playback_bleed_segment_is_attributed_and_dropped() -> None:
    # Given: own playback active inside the grace window.
    # NOTE (turn/barge-in fix): this replaces
    # test_grace_gates_only_the_interrupt_not_capture_or_asr, which codified the
    # old behavior where a bleed segment still flowed to ASR during the grace.
    # Segments recorded while our own voice is out without a real barge-in are
    # now attributed to the speaker bleed and dropped, so Whisper never wastes
    # a pass transcribing ourselves.
    manager = PluginManager()
    interrupts = InterruptRecorder()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(barge_in_grace_ms=500.0, vad_scores=[0.9, 0.1, 0.1])
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    capture = LogCapture()
    try:
        # When: one full utterance (speech + silence boundary) is captured.
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        await manager.wait_for_idle()
        await asyncio.sleep(0.6)

        # Then: nothing flows to ASR, no interrupt fires, and the drop is logged.
        assert recorder.chunks == []
        assert interrupts.interrupts == []
        assert any("attributed to own playback, dropped" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


def test_default_barge_in_grace_is_documented_and_configurable() -> None:
    # Given: default settings and explicit grace settings.
    defaults = AudioInputConfig.from_settings(make_settings(), source="mic", require_device=False)
    tuned = AudioInputConfig.from_settings(
        make_settings(barge_in_grace_ms=250.0), source="mic", require_device=False
    )

    # Then: the default knob is 800 ms and a TOML/plugin override is honored.
    assert defaults.barge_in_grace_ms == 800.0
    assert tuned.barge_in_grace_ms == 250.0


def test_new_knob_defaults_and_overrides() -> None:
    # Given: default settings and fully tuned settings.
    defaults = AudioInputConfig.from_settings(make_settings(), source="mic", require_device=False)
    tuned = AudioInputConfig.from_settings(
        make_settings(
            barge_in_level_factor=2.0,
            barge_in_min_speech_ms=500.0,
            turn_silence_timeout=1.0,
            max_turn_secs=10.0,
        ),
        source="mic",
        require_device=False,
    )

    # Then: level/sustained/turn knobs carry their defaults and honor overrides.
    assert defaults.barge_in_level_factor == 1.3
    assert defaults.barge_in_min_speech_ms == 300.0
    assert defaults.turn_silence_timeout == 2.0
    assert defaults.max_turn_secs == 30.0
    assert tuned.barge_in_level_factor == 2.0
    assert tuned.barge_in_min_speech_ms == 500.0
    assert tuned.turn_silence_timeout == 1.0
    assert tuned.max_turn_secs == 10.0


@pytest.mark.asyncio
async def test_repeated_playback_chunks_keep_single_grace_window() -> None:
    # Given: playback started (one grace window open).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(
        barge_in_grace_ms=10_000.0, vad_scores=[0.9], cycle_last=True
    )
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    first_stamp = microphone._playback_started_at

    # When: the TTS streams many non-final chunks (one utterance, many events).
    await asyncio.sleep(0.05)
    for _ in range(5):
        await microphone.on_audio_output(
            AudioOutput(
                samples=PLAYBACK_CHUNK,
                sample_rate=24_000,
                channels=1,
                format="pcm_s16le",
                final=False,
            )
        )

    # Then: the grace window is NOT re-stamped and the playback level is tracked.
    assert microphone._playback_active
    assert microphone._playback_started_at == first_stamp
    assert microphone._playback_rms > 0.0
    assert interrupts.interrupts == []
    await manager.close()


@pytest.mark.asyncio
async def test_loud_sustained_speech_over_quiet_playback_interrupts() -> None:
    # Given: own playback past its grace with a quiet level, and a user voice
    # that has been loud and sustained (the stamping-regression scenario: with
    # the old per-chunk re-stamp this could never fire mid-playback).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(vad_scores=[0.9], cycle_last=True)
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    microphone._playback_started_at = monotonic() - 5.0
    microphone._playback_rms = 0.05
    microphone._speech_onset_at = monotonic() - 1.0
    capture = LogCapture()
    try:
        # When: a loud mic frame arrives (VAD speech, far above 0.05 * 1.3).
        factory.captures[0].emit(LOUD_FRAME)
        await asyncio.wait_for(interrupts.received.wait(), timeout=1)
        await manager.wait_for_idle()

        # Then: the playback is cut immediately and the grant is logged w/ numbers.
        assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
        assert not microphone._playback_active
        assert any("barge-in granted" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_quiet_mic_below_playback_level_does_not_interrupt() -> None:
    # Given: own playback past its grace but LOUD (speaker bleed dominates).
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(vad_scores=[0.9, 0.1, 0.1])
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    microphone._playback_started_at = monotonic() - 5.0
    microphone._playback_rms = 0.4
    capture = LogCapture()
    try:
        # When: the VAD fires on a near-silent mic frame (pure bleed pickup).
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
        await manager.wait_for_idle()
        await asyncio.sleep(0.1)

        # Then: no interrupt, with the bleed reason logged.
        assert interrupts.interrupts == []
        assert any("reason=bleed" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_loud_but_brief_speech_does_not_interrupt() -> None:
    # Given: own playback past its grace with a quiet level.
    manager = PluginManager()
    interrupts = InterruptRecorder()
    microphone, factory = make_microphone(vad_scores=[0.9, 0.1, 0.1])
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)
    microphone._playback_started_at = monotonic() - 5.0
    microphone._playback_rms = 0.05
    capture = LogCapture()
    try:
        # When: a single loud frame arrives (onset just now, below 300 ms).
        factory.captures[0].emit(LOUD_FRAME)
        await manager.wait_for_idle()
        await asyncio.sleep(0.1)

        # Then: no interrupt yet — a spike is not a barge-in.
        assert interrupts.interrupts == []
        assert any("reason=too-short" in line for line in capture.lines)
    finally:
        capture.stop()
        await manager.close()


@pytest.mark.asyncio
async def test_consecutive_segments_merge_into_one_turn_chunk() -> None:
    # Given: no playback, a short turn window, and two quick utterances.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=0.5,
        silence_timeout=0.1,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)

    # When: two segments arrive closer together than the turn timeout.
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.sleep(0.05)
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
    await asyncio.sleep(0.6)
    await manager.wait_for_idle()

    # Then: exactly one audio_chunk carries both segments concatenated.
    assert len(recorder.chunks) == 1
    seg = SPEECH_FRAME + SILENCE_FRAME
    assert recorder.chunks[0].samples == seg + seg
    await manager.close()


@pytest.mark.asyncio
async def test_turn_flush_after_silence_emits_single_chunk() -> None:
    # Given: no playback and a short turn window.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=0.3, silence_timeout=0.1, vad_scores=[0.9, 0.1, 0.1]
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)

    # When: one segment closes and silence outlasts the turn timeout.
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
    await asyncio.sleep(0.5)
    await manager.wait_for_idle()

    # Then: one chunk, not one per segment plus one per flush.
    assert len(recorder.chunks) == 1
    assert recorder.chunks[0].samples == SPEECH_FRAME + SILENCE_FRAME
    await manager.close()


@pytest.mark.asyncio
async def test_max_turn_secs_flushes_accumulated_buffer() -> None:
    # Given: no playback, a long turn window but a tiny hard cap.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    microphone, factory = make_microphone(
        turn_silence_timeout=10.0,
        max_turn_secs=0.25,
        silence_timeout=0.1,
        vad_scores=[0.9, 0.1, 0.9, 0.1, 0.9, 0.1],
    )
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)

    # When: segments keep arriving without a long enough pause to flush by time.
    for _ in range(3):
        factory.captures[0].emit(SPEECH_FRAME)
        factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=2)
    await manager.wait_for_idle()

    # Then: the cap flushed what was accumulated (one chunk, >= cap duration).
    assert len(recorder.chunks) == 1
    assert recorder.chunks[0].duration_ms >= 250.0
    await manager.close()
