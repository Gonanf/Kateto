from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from time import monotonic
from typing import Any
import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import (
    AudioData,
    AudioOutput,
    GenerateData,
    InterruptData,
    SpeakRequestData,
)
from kateto.plugins.audio_input.base import (
    AudioInputConfig,
    AudioInputConfigurationError,
    AudioInputLifecycleError,
    SileroVad,
)
from kateto.plugins.audio_input.mask import (
    MaskAudioInput,
    MaskCapture,
    MaskCaptureFactory,
    get_mask_capture_factory,
)
import kateto.plugins.audio_input.mask as mask_module
from kateto.plugins.audio_input.mic import MicrophoneAudioInput
from kateto.plugins.system.voice_manager import VoiceManager

SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600


@pytest.fixture(autouse=True)
def _reset_mask_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the singleton factory before each test to prevent cross-test bleed."""
    monkeypatch.setattr(mask_module, "_MASK_CAPTURE_FACTORY", None)


class FixtureSileroModel:
    """Deterministic Silero model popping scores in FIFO order."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = deque(scores)

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        assert samples
        assert sample_rate == 16_000
        return self._scores.popleft()


class SequencedSileroModel:
    """Deterministic Silero model that cycles the last score once exhausted."""

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
    """Simulated sound capture for tests."""

    def __init__(self, callback: Callable[[bytes, int, None, None], None]) -> None:
        self._callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def emit(self, samples: bytes) -> None:
        self._callback(samples, len(samples) // 2, None, None)


class FixtureCaptureFactory:
    """Factory creating FixtureCapture instances."""

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
    """Event subscriber sink that records audio_chunk events."""

    def __init__(self) -> None:
        super().__init__("audio_recorder")
        self.chunks: list[AudioData] = []
        self.chunk_received = asyncio.Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.chunks.append(data)
        self.chunk_received.set()


class InterruptRecorder(Plugin):
    """Event subscriber sink that records interrupt events."""

    def __init__(self) -> None:
        super().__init__("interrupt_recorder")
        self.interrupts: list[InterruptData] = []
        self.received = asyncio.Event()

    async def on_interrupt(self, data: InterruptData) -> None:
        self.interrupts.append(data)
        self.received.set()


class DynamicVoicePlugin(Plugin):
    """Dynamic voice plugin that declares voice capability."""

    def __init__(self, name: str) -> None:
        super().__init__(name, capabilities=("voice",))
        self.prompts: list[str | None] = []
        self.received_speaks: list[SpeakRequestData] = []

    async def on_generate(self, data: GenerateData) -> None:
        self.prompts.append(data.prompt)

    async def on_speak(self, data: SpeakRequestData) -> None:
        self.received_speaks.append(data)


# ---------------------------------------------------------------------------
# A. Contrato de push
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"sample_rate": 8_000}, "sample_rate"),
        ({"sample_rate": 22_050}, "sample_rate"),
        ({"sample_rate": 48_000}, "sample_rate"),
        ({"channels": 2}, "channels"),
        ({"channels": 0}, "channels"),
        ({"format": "wav"}, "format"),
        ({"format": "pcm_s32le"}, "format"),
    ],
)
def test_mask_push_rejects_invalid_configuration(kwargs: dict[str, Any], field: str) -> None:
    # Given: a MaskCaptureFactory with an active capture created.
    factory = MaskCaptureFactory()
    config = AudioInputConfig.from_settings(PluginSettings(), source="mask", require_device=False)
    capture = factory.create(
        config,
        lambda samples, frames, time_info, status: None,
    )
    capture.start()

    # When / Then: pushing with invalid configuration parameters raises AudioInputConfigurationError.
    with pytest.raises(AudioInputConfigurationError) as exc_info:
        factory.push(b"\x01\x00" * 100, **kwargs)
    assert exc_info.value.field == field


@pytest.mark.parametrize(
    "samples",
    [
        b"",
        b"\x01",
        b"\x01\x02\x03",
        b"\x01\x02\x03\x04\x05",
    ],
)
def test_mask_push_rejects_empty_or_odd_length_bytes(samples: bytes) -> None:
    # Given: a MaskCaptureFactory with an active capture.
    factory = MaskCaptureFactory()
    config = AudioInputConfig.from_settings(PluginSettings(), source="mask", require_device=False)
    capture = factory.create(
        config,
        lambda s, f, t, st: None,
    )
    capture.start()

    # When / Then: pushing empty or odd-length bytes raises ValueError.
    with pytest.raises(ValueError, match="non-empty, even-length PCM s16LE"):
        factory.push(samples)


def test_mask_push_without_create_raises_lifecycle_error() -> None:
    # Given: a factory with no create() called yet.
    factory = MaskCaptureFactory()

    # When / Then: pushing audio raises AudioInputLifecycleError.
    with pytest.raises(AudioInputLifecycleError):
        factory.push(b"\x01\x00" * 100)


def test_mask_capture_feed_before_start_does_not_deliver() -> None:
    # Given: a MaskCapture instance created but not started.
    delivered: list[bytes] = []
    capture = MaskCapture(lambda samples, frames, time_info, status: delivered.append(samples))

    # When: feed is called before start().
    capture.feed(b"\x01\x00" * 100)

    # Then: callback is not invoked.
    assert delivered == []


def test_mask_push_valid_delivers_exact_frame_and_sets_voice() -> None:
    # Given: a factory with a started capture.
    factory = MaskCaptureFactory()
    delivered: list[tuple[bytes, int]] = []
    config = AudioInputConfig.from_settings(PluginSettings(), source="mask", require_device=False)
    capture = factory.create(
        config,
        lambda samples, frames, time_info, status: delivered.append((samples, frames)),
    )
    capture.start()

    # When: valid PCM audio is pushed with voice="doktor".
    frame = b"\x01\x00" * 800
    factory.push(frame, voice="doktor")

    # Then: callback receives the exact frame and frame count (len // 2).
    assert delivered == [(frame, 800)]
    assert factory.voice == "doktor"


def test_get_mask_capture_factory_singleton() -> None:
    # Given / When: multiple invocations of get_mask_capture_factory.
    f1 = get_mask_capture_factory()
    f2 = get_mask_capture_factory()

    # Then: the exact same singleton instance is returned.
    assert f1 is f2


# ---------------------------------------------------------------------------
# B. 4 voces simultáneas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("voice_id", ["doktor", "jane", "whisperer", "conquest"])
async def test_mask_audio_chunk_carries_voice_and_target_none(voice_id: str) -> None:
    # Given: MaskAudioInput enabled on a manager with a recording sink.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    vad = SileroVad(FixtureSileroModel([0.9, 0.1, 0.1]), threshold=0.5)
    settings = PluginSettings(sample_rate=16_000, silence_timeout=0.1, turn_silence_timeout=0.1)
    mask = MaskAudioInput(settings, vad=vad)

    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mask)
    factory = get_mask_capture_factory()

    try:
        # When: mask audio frames arrive with the specified voice ID.
        factory.push(SPEECH_FRAME, voice=voice_id)
        await asyncio.sleep(0)
        factory.push(SILENCE_FRAME)
        await asyncio.sleep(0)
        factory.push(SILENCE_FRAME)

        await asyncio.wait_for(recorder.chunk_received.wait(), timeout=1.0)
        await manager.wait_for_idle()

        # Then: audio_chunk payload carries the voice ID and source="mask".
        assert len(recorder.chunks) == 1
        chunk = recorder.chunks[0]
        assert chunk.voice == voice_id
        assert chunk.source == "mask"

        # And: envelope target is None (the voice must NOT be in envelope.target,
        # otherwise subscriber resolution would filter it out before reaching ASR).
        envelope = next(e for e in manager.get_events() if e.name == "audio_chunk")
        assert envelope.target is None
        assert envelope.data.voice == voice_id
        assert envelope.source == "audio_input_mask/mask"
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# C. Propagación de voz hasta VoiceManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_propagation_to_voice_manager() -> None:
    # Given: VoiceManager and 4 dynamic voice plugins enabled.
    manager = PluginManager()
    voice_manager = VoiceManager()
    await manager.enable_plugin(voice_manager)

    voices = {
        name: DynamicVoicePlugin(name)
        for name in ("doktor", "jane", "whisperer", "conquest")
    }
    for plugin in voices.values():
        await manager.enable_plugin(plugin)

    try:
        # When: a generate event arrives with voice="conquest".
        await manager.emit(
            "generate",
            GenerateData(prompt="Coordinate deployment release", voice="conquest"),
            source="classifier",
        )
        await manager.wait_for_idle()

        # Then: VoiceManager routes speak directly to conquest without lottery.
        speak_events = [e for e in manager.get_events() if e.name == "speak"]
        assert len(speak_events) == 1
        speak_event = speak_events[0]
        assert speak_event.target == "conquest"
        assert speak_event.data.voice == "conquest"
        assert speak_event.data.prompt == "Coordinate deployment release"

        # And: the conquest plugin received the speak request, while others did not.
        assert len(voices["conquest"].received_speaks) == 1
        assert voices["conquest"].received_speaks[0].prompt == "Coordinate deployment release"
        for other_voice in ("doktor", "jane", "whisperer"):
            assert len(voices[other_voice].received_speaks) == 0
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# D. Barge-in por el listener del mask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mask_barge_in_on_sustained_speech_during_playback() -> None:
    # Given: MaskAudioInput with playback active and deterministic VAD scores.
    manager = PluginManager()
    interrupts = InterruptRecorder()
    vad = SileroVad(SequencedSileroModel([0.9], cycle_last=True), threshold=0.5)
    settings = PluginSettings(
        sample_rate=16_000,
        silence_timeout=0.2,
        turn_silence_timeout=0.2,
        barge_in_grace_ms=100.0,
        barge_in_min_speech_ms=100.0,
        barge_in_level_factor=0.0,
        interrupt_on_vad=True,
        interrupt_gate="off",
    )
    mask = MaskAudioInput(settings, vad=vad)

    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(mask)
    factory = get_mask_capture_factory()

    try:
        # When: active playback is signalled via AudioOutput.
        await manager.emit(
            "audio_output",
            AudioOutput(samples=b"", sample_rate=16_000, channels=1, final=False),
            source="audio_output",
        )
        await manager.wait_for_idle()
        assert mask._playback_active

        # And: sustained speech frames keep arriving into the mask stream past the grace window.
        deadline = monotonic() + 5.0
        while not interrupts.received.is_set():
            factory.push(SPEECH_FRAME)
            await asyncio.sleep(0.05)
            assert monotonic() < deadline, "barge-in never fired past the grace window"

        await manager.wait_for_idle()

        # Then: an interrupt event is emitted for voice activity and playback state is reset.
        assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
        assert not mask._playback_active
    finally:
        await manager.close()


# ---------------------------------------------------------------------------
# E. Independencia de fuentes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_independence_between_mask_and_microphone() -> None:
    # Given: both microphone and mask inputs enabled on the same manager.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    await manager.enable_plugin(recorder)

    mic_factory = FixtureCaptureFactory()
    mic_vad = SileroVad(FixtureSileroModel([0.9, 0.1, 0.1]), threshold=0.5)
    mic = MicrophoneAudioInput(
        PluginSettings(device="fixture", silence_timeout=0.1, turn_silence_timeout=0.1),
        vad=mic_vad,
        capture_factory=mic_factory,
    )
    await manager.enable_plugin(mic)

    mask_vad = SileroVad(FixtureSileroModel([0.9, 0.1, 0.1]), threshold=0.5)
    mask = MaskAudioInput(
        PluginSettings(silence_timeout=0.1, turn_silence_timeout=0.1),
        vad=mask_vad,
    )
    await manager.enable_plugin(mask)
    mask_factory = get_mask_capture_factory()

    try:
        # When: mask input emits a speech segment with a voice specified.
        mask_factory.push(SPEECH_FRAME, voice="jane")
        await asyncio.sleep(0)
        mask_factory.push(SILENCE_FRAME)
        await asyncio.sleep(0)
        mask_factory.push(SILENCE_FRAME)

        await asyncio.sleep(0.15)
        await manager.wait_for_idle()

        # And: microphone input emits a speech segment without any voice.
        mic_factory.captures[0].emit(SPEECH_FRAME)
        await asyncio.sleep(0)
        mic_factory.captures[0].emit(SILENCE_FRAME)
        await asyncio.sleep(0)
        mic_factory.captures[0].emit(SILENCE_FRAME)

        await asyncio.sleep(0.15)
        await manager.wait_for_idle()

        # Then: two chunks were recorded by the sink.
        assert len(recorder.chunks) == 2
        mask_chunk = recorder.chunks[0]
        mic_chunk = recorder.chunks[1]

        # And: mask chunk has source="mask" and voice="jane".
        assert mask_chunk.source == "mask"
        assert mask_chunk.voice == "jane"

        # And: microphone chunk has mic source and voice is None.
        assert mic_chunk.source in ("mic", "microphone")
        assert mic_chunk.voice is None
    finally:
        await manager.close()
