from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections import deque
from collections.abc import Callable

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, AudioInputStatus, AudioInputStatusData, InterruptData
from kateto.plugins.audio_input.base import (
    AudioDeviceError,
    AudioInputConfig,
    AudioInputConfigurationError,
    CallbackQueue,
    SileroVad,
)
from kateto.plugins.audio_input.meet import MeetAudioInput
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


SPEECH_FRAME = b"\x01\x00" * 1_600
SILENCE_FRAME = b"\x00\x00" * 1_600


class FixtureSileroModel:
    def __init__(self, scores: list[float]) -> None:
        self._scores = deque(scores)

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        assert samples
        assert sample_rate == 16_000
        return self._scores.popleft()


class FixtureCapture:
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
    def __init__(self) -> None:
        self.captures: list[FixtureCapture] = []
        self.requests: list[AudioInputConfig] = []

    def create(
        self,
        config: AudioInputConfig,
        callback: Callable[[bytes, int, None, None], None],
    ) -> FixtureCapture:
        if config.device == "missing":
            raise AudioDeviceError(
                source="audio_input_meet",
                device=config.device,
                reason="select an installed loopback or virtual input device",
            )
        capture = FixtureCapture(callback)
        self.captures.append(capture)
        self.requests.append(config)
        return capture


class RecordingAudioPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("audio_recorder")
        self.chunks: list[AudioData] = []
        self.chunk_received = asyncio.Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.chunks.append(data)
        self.chunk_received.set()


class BlockingAudioPlugin(RecordingAudioPlugin):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.chunks.append(data)
        self.chunk_received.set()
        await self.release.wait()
        self.finished.set()


class InterruptRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__("interrupt_recorder")
        self.interrupts: list[InterruptData] = []
        self.received = asyncio.Event()

    async def on_interrupt(self, data: InterruptData) -> None:
        self.interrupts.append(data)
        self.received.set()


def make_vad(scores: list[float]) -> SileroVad:
    return SileroVad(FixtureSileroModel(scores), threshold=0.5)


def make_settings(*, device: str = "fixture", silence_timeout: float = 0.2) -> PluginSettings:
    return PluginSettings(
        device=device,
        sample_rate=16_000,
        silence_timeout=silence_timeout,
        vad_model="silero",
        interrupt_on_vad=True,
    )


@pytest.mark.asyncio
async def test_emits_pcm_s16le_at_silence_boundary_with_mic_metadata() -> None:
    # Given: a microphone capture with one speech frame followed by its silence timeout.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(make_settings(), vad=make_vad([0.9, 0.1, 0.1]), capture_factory=factory)
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)

    # When: the callback receives speech and two 100 ms silent frames.
    capture = factory.captures[0]
    capture.emit(SPEECH_FRAME)
    capture.emit(SILENCE_FRAME)
    capture.emit(SILENCE_FRAME)
    assert not any(event.name == "audio_chunk" for event in manager.get_events())
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: one PCM s16LE chunk preserves its boundary, format, and mic source tags.
    assert recorder.chunks == [
        AudioData(
            samples=SPEECH_FRAME + SILENCE_FRAME + SILENCE_FRAME,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mic",
            duration_ms=300.0,
        ),
    ]
    envelope = next(event for event in manager.get_events() if event.name == "audio_chunk")
    assert envelope.source == "audio_input_mic/mic"
    assert factory.requests[0].device == "fixture"
    await manager.close()


@pytest.mark.asyncio
async def test_meet_uses_configured_loopback_and_tags_its_source() -> None:
    # Given: a configured Meet loopback capture and a deterministic Silero score.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    factory = FixtureCaptureFactory()
    meet = MeetAudioInput(make_settings(device="Meet Loopback", silence_timeout=0.1), vad=make_vad([0.9, 0.1]), capture_factory=factory)
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(meet)

    # When: the loopback callback receives one utterance and its silence boundary.
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: the chunk and event envelope identify Meet rather than microphone input.
    assert recorder.chunks[0].source == "meet"
    envelope = next(event for event in manager.get_events() if event.name == "audio_chunk")
    assert envelope.source == "audio_input_meet/meet"
    assert factory.requests[0].device == "Meet Loopback"
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("plugin_type", "device", "source"),
    [
        (MicrophoneAudioInput, "fixture", "audio_input_mic/mic"),
        (MeetAudioInput, "Meet Loopback", "audio_input_meet/meet"),
    ],
)
async def test_audio_inputs_emit_typed_idle_and_recording_status(
    plugin_type: type[MicrophoneAudioInput] | type[MeetAudioInput],
    device: str,
    source: str,
) -> None:
    # Given: an enabled microphone or Meet capture with deterministic VAD.
    manager = PluginManager()
    factory = FixtureCaptureFactory()
    plugin = plugin_type(
        make_settings(device=device, silence_timeout=0.1),
        vad=make_vad([0.9, 0.1, 0.1]),
        capture_factory=factory,
    )
    await manager.enable_plugin(plugin)

    # When: one speech frame reaches the capture, followed by the silence boundary.
    capture = factory.captures[0]
    capture.emit(SPEECH_FRAME)
    capture.emit(SILENCE_FRAME)
    capture.emit(SILENCE_FRAME)
    await asyncio.wait_for(plugin.resumed_listening.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: typed lifecycle events identify recording and return to idle from the same source.
    statuses = [
        event
        for event in manager.get_events()
        if event.name == "audio_input_status"
    ]
    assert [(event.source, event.data) for event in statuses] == [
        (source, AudioInputStatusData(status=AudioInputStatus.IDLE)),
        (source, AudioInputStatusData(status=AudioInputStatus.RECORDING)),
        (source, AudioInputStatusData(status=AudioInputStatus.IDLE)),
    ]
    await manager.close()


def test_callback_queue_rejects_malformed_pcm_and_drops_when_bounded() -> None:
    # Given: a callback queue with capacity for one valid PCM frame.
    queue = CallbackQueue(capacity=1)

    # When: it receives a valid frame, an overflowing frame, and malformed odd-byte PCM.
    accepted = queue.offer(SILENCE_FRAME)
    overflowed = queue.offer(SILENCE_FRAME)
    malformed = queue.offer(b"\x00")

    # Then: the callback path never blocks and records both rejected inputs.
    assert accepted
    assert not overflowed
    assert not malformed
    assert queue.pending == 1
    assert queue.dropped_frames == 1
    assert queue.rejected_frames == 1


@pytest.mark.asyncio
async def test_resumes_listening_before_a_blocked_audio_consumer_finishes() -> None:
    # Given: an audio subscriber that holds the emitted chunk open.
    manager = PluginManager()
    recorder = BlockingAudioPlugin()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(make_settings(silence_timeout=0.1), vad=make_vad([0.9, 0.1]), capture_factory=factory)
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)

    # When: the source reaches the silence boundary.
    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(microphone.resumed_listening.wait(), timeout=1)

    # Then: the listener has resumed in under 50 ms without waiting for downstream work.
    assert microphone.last_resume_gap_ms is not None
    assert microphone.last_resume_gap_ms < 50
    assert not recorder.finished.is_set()
    recorder.release.set()
    await asyncio.wait_for(recorder.finished.wait(), timeout=1)
    await manager.close()


@pytest.mark.asyncio
async def test_vad_interrupts_active_playback_once_per_playback_window() -> None:
    # Given: an audio input listening while playback is active.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    interrupts = InterruptRecorder()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(make_settings(), vad=make_vad([0.9, 0.9, 0.1, 0.1]), capture_factory=factory)
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)
    microphone.set_playback_active(True)

    # When: VAD sees repeated speech before the segment closes.
    capture = factory.captures[0]
    capture.emit(SPEECH_FRAME)
    capture.emit(SPEECH_FRAME)
    capture.emit(SILENCE_FRAME)
    capture.emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=1)
    await asyncio.wait_for(interrupts.received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: the manager receives one immediate interrupt rather than one per speech frame.
    assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
    await manager.close()


@pytest.mark.asyncio
async def test_vad_interrupts_llm_even_when_output_status_is_idle() -> None:
    manager = PluginManager()
    interrupts = InterruptRecorder()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(
        make_settings(), vad=make_vad([0.9, 0.1]), capture_factory=factory
    )
    await manager.enable_plugin(interrupts)
    await manager.enable_plugin(microphone)

    factory.captures[0].emit(SPEECH_FRAME)
    factory.captures[0].emit(SILENCE_FRAME)
    await asyncio.wait_for(interrupts.received.wait(), timeout=1)

    assert [item.reason for item in interrupts.interrupts] == ["voice_activity"]
    await manager.close()


@pytest.mark.asyncio
async def test_missing_meet_device_returns_actionable_error_without_capture_task() -> None:
    # Given: a Meet source configured with a missing OS loopback device.
    manager = PluginManager()
    factory = FixtureCaptureFactory()
    meet = MeetAudioInput(make_settings(device="missing"), vad=make_vad([]), capture_factory=factory)

    # When: the plugin is enabled through the normal manager lifecycle.
    with pytest.raises(AudioDeviceError, match="installed loopback or virtual input device"):
        await manager.enable_plugin(meet)

    # Then: capture never starts and the actionable error identifies the configured device.
    assert meet.capture_task is None
    assert factory.captures == []
    await manager.close()


def test_rejects_non_16khz_config_before_starting_capture() -> None:
    # Given: an otherwise valid microphone config with an unsupported sample rate.
    settings = PluginSettings(sample_rate=8_000, silence_timeout=0.2, vad_model="silero")

    # When: the microphone plugin parses its supplied config.
    with pytest.raises(AudioInputConfigurationError, match="sample_rate"):
        MicrophoneAudioInput(settings, vad=make_vad([]), capture_factory=FixtureCaptureFactory())

    # Then: no PortAudio stream is created for malformed capture configuration.


@pytest.mark.asyncio
async def test_disable_and_reenable_discards_stale_callback_frames() -> None:
    # Given: a microphone that is disabled before its original callback can be reused.
    manager = PluginManager()
    recorder = RecordingAudioPlugin()
    factory = FixtureCaptureFactory()
    microphone = MicrophoneAudioInput(make_settings(), vad=make_vad([0.9, 0.1, 0.1]), capture_factory=factory)
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(microphone)
    stale_capture = factory.captures[0]
    await manager.disable_plugin(microphone.name)
    await manager.enable_plugin(microphone)

    # When: the stale callback fires after resume and the new capture provides one utterance.
    stale_capture.emit(SPEECH_FRAME)
    fresh_capture = factory.captures[1]
    fresh_capture.emit(SPEECH_FRAME)
    fresh_capture.emit(SILENCE_FRAME)
    fresh_capture.emit(SILENCE_FRAME)
    await asyncio.wait_for(recorder.chunk_received.wait(), timeout=1)
    await manager.wait_for_idle()

    # Then: only the current capture contributes audio after the listener resumes.
    assert recorder.chunks[0].samples == SPEECH_FRAME + SILENCE_FRAME + SILENCE_FRAME
    assert stale_capture.stopped
    assert stale_capture.closed
    await manager.close()
