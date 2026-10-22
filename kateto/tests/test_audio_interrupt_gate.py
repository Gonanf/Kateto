from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic

import httpx
import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, AudioOutput, InterruptData, TranscriptionData
from kateto.plugins.audio_input.base import (
    DEFAULT_INTERRUPT_GATE_IGNORE_WORDS,
    AudioInputConfig,
    AudioInputConfigurationError,
    SileroVad,
)
from kateto.plugins.audio_input.listener import _normalize_text, evaluate_gate_lexical
from kateto.plugins.audio_input.mic import MicrophoneAudioInput


SPEECH_FRAME = b"\x01\x00" * 1_600  # 100 ms at 16 kHz mono s16LE
SILENCE_FRAME = b"\x00\x00" * 1_600
LOUD_FRAME = b"\xff\x7f" * 1_600  # 100 ms near full-scale: loud user voice
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


class InterruptRecorder(Plugin):
    def __init__(self) -> None:
        super().__init__("interrupt_recorder")
        self.interrupts: list[InterruptData] = []
        self.received = asyncio.Event()

    async def on_interrupt(self, data: InterruptData) -> None:
        self.interrupts.append(data)
        self.received.set()


class CannedWhisper:
    def __init__(self, responses: list[str] | str, delay_s: float = 0.0) -> None:
        if isinstance(responses, str):
            self._responses = [responses]
        else:
            self._responses = list(responses)
        self._idx = 0
        self._delay_s = delay_s
        self.calls: list[bytes] = []

    async def transcribe_samples(self, samples: bytes, **kwargs) -> TranscriptionData:
        self.calls.append(samples)
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        text = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return TranscriptionData(text=text)


class CannedClassifier:
    def __init__(
        self,
        category: str = "EXECUTE",
        confidence: float = 0.9,
        *,
        delay_s: float = 0.0,
        fail: bool = False,
    ) -> None:
        self.category = category
        self.confidence = confidence
        self.delay_s = delay_s
        self.fail = fail
        self.calls: list[str] = []

    async def classify(self, text: str) -> tuple[str, float]:
        self.calls.append(text)
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise httpx.ConnectError("classifier connection failed")
        return self.category, self.confidence


def make_vad(scores: list[float], *, cycle_last: bool = False) -> SileroVad:
    return SileroVad(SequencedSileroModel(scores, cycle_last=cycle_last), threshold=0.5)


def make_settings(
    *,
    interrupt_gate: str = "off",
    interrupt_gate_window_ms: int = 1200,
    interrupt_gate_timeout_ms: int = 800,
    interrupt_gate_min_confidence: float = 0.4,
    interrupt_gate_ignore_words: list[str] | None = None,
    interrupt_gate_classifier_url: str = "http://127.0.0.1:8091/v1/chat/completions",
    interrupt_gate_model: str = "",
    interrupt_gate_backend: str = "same",
    interrupt_gate_endpoint: str = "http://127.0.0.1:8092",
    silence_timeout: float = 0.2,
    barge_in_grace_ms: float = 0.0,
    barge_in_level_factor: float = 1.0,
    barge_in_min_speech_ms: float = 0.0,
) -> PluginSettings:
    return PluginSettings(
        device="fixture",
        sample_rate=16_000,
        silence_timeout=silence_timeout,
        vad_model="silero",
        interrupt_on_vad=True,
        barge_in_grace_ms=barge_in_grace_ms,
        barge_in_level_factor=barge_in_level_factor,
        barge_in_min_speech_ms=barge_in_min_speech_ms,
        interrupt_gate=interrupt_gate,
        interrupt_gate_window_ms=interrupt_gate_window_ms,
        interrupt_gate_timeout_ms=interrupt_gate_timeout_ms,
        interrupt_gate_min_confidence=interrupt_gate_min_confidence,
        interrupt_gate_ignore_words=interrupt_gate_ignore_words,
        interrupt_gate_classifier_url=interrupt_gate_classifier_url,
        interrupt_gate_model=interrupt_gate_model,
        interrupt_gate_backend=interrupt_gate_backend,
        interrupt_gate_endpoint=interrupt_gate_endpoint,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    [
        "ummm si",
        "ajá",
        "claro, dale",
    ],
)
async def test_gate_lexical_ignore_words_do_not_interrupt(phrase: str) -> None:
    # Given: a microphone configured with interrupt_gate="lexical" and canned ASR returning backchannel
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
        silence_timeout=0.2,
    )
    whisper = CannedWhisper(phrase)
    factory = FixtureCaptureFactory()
    # 4 speech frames (400ms sustained) then silence frames
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    # Playback active (Kateto is speaking)
    mic.set_playback_active(True)

    # When: user speaks a muletilla ("ummm si", "ajá", or "claro, dale")
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    # User stops speaking (silence)
    for _ in range(3):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    # Allow drain queue and gate task to execute
    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: playback is NOT interrupted and no interrupt event was emitted
    assert len(recorder.interrupts) == 0
    assert mic._playback_active is True

    await manager.close()


@pytest.mark.asyncio
async def test_gate_lexical_real_turn_interrupts() -> None:
    # Given: microphone with lexical gate and canned ASR returning a real command
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
    )
    whisper = CannedWhisper("che, pará un segundo")
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks "che, pará un segundo"
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: Kateto is interrupted
    assert len(recorder.interrupts) == 1
    assert recorder.interrupts[0].reason == "voice_activity"
    assert mic._playback_active is False

    await manager.close()


@pytest.mark.asyncio
async def test_gate_growing_speech_case_6_interrupts() -> None:
    # Given: a user utterance that grows from muletilla "umm si" to "umm si che pará"
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_timeout_ms=800,
        barge_in_grace_ms=0.0,
        silence_timeout=0.4,
    )
    # Sequence of ASR transcriptions as utterance grows
    whisper = CannedWhisper(["umm si", "umm si che pará"])
    factory = FixtureCaptureFactory()
    # 3 frames speech (300ms) -> 1 frame silence (pause) -> 4 frames speech ("che pará") -> silence
    vad_scores = [0.9, 0.9, 0.9, 0.1, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user begins with "umm si"
    for _ in range(3):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    capture.emit(SILENCE_FRAME)
    await asyncio.sleep(0.05)
    # The first gate check ran and ignored
    assert len(recorder.interrupts) == 0

    # User continues speaking: "... che pará"
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: gate re-evaluated the accumulated text, recognized non-muletilla, and interrupted!
    assert len(recorder.interrupts) == 1
    assert recorder.interrupts[0].reason == "voice_activity"
    assert mic._playback_active is False

    await manager.close()


@pytest.mark.asyncio
async def test_gate_timeout_failsafe_interrupts() -> None:
    # Given: ASR takes 400ms, but timeout_ms is set to 150ms
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_timeout_ms=150,
        barge_in_grace_ms=0.0,
    )
    whisper = CannedWhisper("ummm si", delay_s=0.4)
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks
    for _ in range(3):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    capture.emit(SILENCE_FRAME)
    # Wait for the timeout to elapse
    await asyncio.sleep(0.25)

    # Then: timeout fail-safe fires and interrupts playback anyway
    assert len(recorder.interrupts) == 1
    assert recorder.interrupts[0].reason in ("gate_timeout", "voice_activity")
    assert mic._playback_active is False

    await manager.close()


@pytest.mark.asyncio
async def test_gate_classifier_server_down_failsafe_interrupts() -> None:
    # Given: interrupt_gate="classifier", a phrase not in ignore_words, and classifier server down
    settings = make_settings(
        interrupt_gate="classifier",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
    )
    whisper = CannedWhisper("debo revisar esto luego")
    classifier = CannedClassifier(fail=True)
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
        classifier_client=classifier,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: speech arrives and classifier fails
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: fail-safe interrupts playback
    assert len(recorder.interrupts) == 1
    assert mic._playback_active is False

    await manager.close()


@pytest.mark.asyncio
async def test_gate_classifier_ignore_self_talk_does_not_interrupt() -> None:
    # Given: classifier returning IGNORE_SELF_TALK with high confidence
    settings = make_settings(
        interrupt_gate="classifier",
        interrupt_gate_timeout_ms=500,
        interrupt_gate_min_confidence=0.4,
        barge_in_grace_ms=0.0,
    )
    whisper = CannedWhisper("I need to remember that")
    classifier = CannedClassifier(category="IGNORE_SELF_TALK", confidence=0.88)
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
        classifier_client=classifier,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user mutters self-talk
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: classifier ignores self-talk and playback continues
    assert len(recorder.interrupts) == 0
    assert mic._playback_active is True

    await manager.close()


@pytest.mark.asyncio
async def test_gate_off_preserves_acoustic_barge_in() -> None:
    # Given: interrupt_gate="off" (default)
    settings = make_settings(
        interrupt_gate="off",
        barge_in_grace_ms=0.0,
    )
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    # Then: acoustic qualification immediately interrupts without waiting for semantic gate
    assert len(recorder.interrupts) == 1
    assert recorder.interrupts[0].reason == "voice_activity"
    assert mic._playback_active is False

    await manager.close()


@pytest.mark.asyncio
async def test_gate_discarded_audio_not_in_turn_buffer() -> None:
    # Given: microphone with lexical gate and "ummm si"
    settings = make_settings(
        interrupt_gate="lexical",
        silence_timeout=0.1,
        barge_in_grace_ms=0.0,
    )
    whisper = CannedWhisper("ummm si")
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.1, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks "ummm si" and then stops, closing the segment
    for _ in range(3):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(3):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.05)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.1)

    # Then: the discarded audio does NOT enter turn_buffer
    assert len(recorder.interrupts) == 0
    assert len(mic.turn_buffer) == 0

    await manager.close()


def test_gate_invalid_config_raises_error() -> None:
    # Given: invalid interrupt_gate value
    settings = PluginSettings(
        device="fixture",
        interrupt_gate="magic",
    )
    factory = FixtureCaptureFactory()

    # When/Then: AudioInputConfigurationError is raised
    with pytest.raises(AudioInputConfigurationError) as exc_info:
        MicrophoneAudioInput(
            settings,
            vad=make_vad([]),
            capture_factory=factory,
        )
    assert "interrupt_gate" in str(exc_info.value)


def test_gate_invalid_backend_raises_error() -> None:
    # Given: invalid interrupt_gate_backend value
    settings = PluginSettings(
        device="fixture",
        interrupt_gate="lexical",
        interrupt_gate_backend="magic",
    )
    factory = FixtureCaptureFactory()

    # When/Then: AudioInputConfigurationError is raised
    with pytest.raises(AudioInputConfigurationError) as exc_info:
        MicrophoneAudioInput(
            settings,
            vad=make_vad([]),
            capture_factory=factory,
        )
    assert "interrupt_gate_backend" in str(exc_info.value)


@pytest.mark.parametrize(
    ("phrase", "expected_ignore"),
    [
        ("un o sí claro que sí", True),
        ("ummm", True),
        ("mmm", True),
        ("eh", True),
        ("no", False),
        ("che pará un segundo", False),
        ("sí, dale", True),
        ("sí, hacelo", False),
    ],
)
def test_gate_tolerant_matcher_unit_cases(phrase: str, expected_ignore: bool) -> None:
    # Given: the default ignore words lexicon
    ignore_words = {
        word
        for phrase_str in DEFAULT_INTERRUPT_GATE_IGNORE_WORDS
        for word in _normalize_text(phrase_str).split()
        if word
    }

    # When: evaluated through the tolerant matcher
    is_ignore, norm_text, remaining = evaluate_gate_lexical(phrase, ignore_words)

    # Then: matches expected verdict
    assert is_ignore is expected_ignore, f"Failed for {phrase!r}: norm={norm_text!r} remaining={remaining!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("phrase", "should_interrupt"),
    [
        ("un o sí claro que sí", False),
        ("ummm", False),
        ("mmm", False),
        ("eh", False),
        ("no", True),
        ("che pará un segundo", True),
        ("sí, dale", False),
        ("sí, hacelo", True),
    ],
)
async def test_gate_tolerant_matcher_e2e_phrases(phrase: str, should_interrupt: bool) -> None:
    # Given: microphone with lexical gate and canned Whisper returning the phrase
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
        silence_timeout=0.2,
    )
    whisper = CannedWhisper(phrase)
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
        whisper_transcriber=whisper,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks the phrase
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(3):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: playback interrupted if and only if should_interrupt is True
    if should_interrupt:
        assert len(recorder.interrupts) == 1
        assert recorder.interrupts[0].reason == "voice_activity"
        assert mic._playback_active is False
    else:
        assert len(recorder.interrupts) == 0
        assert mic._playback_active is True

    await manager.close()


@pytest.mark.asyncio
async def test_gate_pywhispercpp_missing_model_failsafe_interrupts() -> None:
    # Given: interrupt_gate_backend="pywhispercpp" with nonexistent model
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_backend="pywhispercpp",
        interrupt_gate_model="/tmp/nonexistent_model_12345.bin",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
    )
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: speech arrives and model cannot be loaded
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: fail-safe interrupts playback and logged warning
    assert len(recorder.interrupts) == 1
    assert mic._playback_active is False
    assert mic._gate_backend_warning_logged is True

    await manager.close()


@pytest.mark.asyncio
async def test_gate_server_unreachable_failsafe_interrupts() -> None:
    # Given: interrupt_gate_backend="server" pointing to inactive port
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_backend="server",
        interrupt_gate_endpoint="http://127.0.0.1:59998",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
    )
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
    )
    recorder = InterruptRecorder()

    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: speech arrives and server is unreachable
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: fail-safe interrupts playback
    assert len(recorder.interrupts) == 1
    assert mic._playback_active is False
    assert mic._gate_backend_warning_logged is True

    await manager.close()


@pytest.mark.asyncio
async def test_gate_server_backend_e2e_ignores_backchannel() -> None:
    # Given: a mock HTTP server responding to whisper-server /inference with backchannel
    settings = make_settings(
        interrupt_gate="lexical",
        interrupt_gate_backend="server",
        interrupt_gate_endpoint="http://127.0.0.1:8092",
        interrupt_gate_timeout_ms=500,
        barge_in_grace_ms=0.0,
    )
    factory = FixtureCaptureFactory()
    vad_scores = [0.9, 0.9, 0.9, 0.9, 0.1, 0.1]
    mic = MicrophoneAudioInput(
        settings,
        vad=make_vad(vad_scores),
        capture_factory=factory,
    )

    # Custom mock transport for mic._http_client
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/inference"
        return httpx.Response(200, json={"text": " un o sí claro que sí.\n"})

    transport = httpx.MockTransport(handler)
    mic._http_client = httpx.AsyncClient(transport=transport)

    recorder = InterruptRecorder()
    manager = PluginManager()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(mic)

    capture = factory.captures[0]
    mic.set_playback_active(True)

    # When: user speaks backchannel
    for _ in range(4):
        capture.emit(LOUD_FRAME)
        await asyncio.sleep(0.01)

    for _ in range(2):
        capture.emit(SILENCE_FRAME)
        await asyncio.sleep(0.01)

    if mic.gate_task is not None:
        await asyncio.wait_for(mic.gate_task, timeout=1.0)
    await asyncio.sleep(0.05)

    # Then: playback is NOT interrupted (IGNORE)
    assert len(recorder.interrupts) == 0
    assert mic._playback_active is True

    await manager.close()

