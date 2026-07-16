from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Final, Protocol

from kateto.core.config import PluginSettings


SAMPLE_RATE: Final = 16_000
CHANNELS: Final = 1
SAMPLE_WIDTH_BYTES: Final = 2
PCM_FORMAT: Final = "pcm_s16le"
DEFAULT_SILENCE_TIMEOUT: Final = 1.5
DEFAULT_VAD_THRESHOLD: Final = 0.5


@dataclass(frozen=True, slots=True)
class AudioInputConfigurationError(Exception):
    field: str
    reason: str

    def __str__(self) -> str:
        return f"invalid audio input configuration for {self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AudioDeviceError(Exception):
    source: str
    device: str
    reason: str

    def __str__(self) -> str:
        return f"{self.source} cannot use configured device {self.device!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AudioInputLifecycleError(Exception):
    plugin: str

    def __str__(self) -> str:
        return f"{self.plugin} must be managed before audio capture starts"


@dataclass(frozen=True, slots=True)
class AudioInputConfig:
    source: str
    device: str
    silence_timeout: float
    vad_threshold: float
    interrupt_on_vad: bool

    @classmethod
    def from_settings(
        cls,
        settings: PluginSettings,
        *,
        source: str,
        require_device: bool,
    ) -> AudioInputConfig:
        sample_rate = SAMPLE_RATE if settings.sample_rate is None else settings.sample_rate
        if sample_rate != SAMPLE_RATE:
            raise AudioInputConfigurationError(
                field="sample_rate",
                reason=f"must be {SAMPLE_RATE} Hz for mono PCM s16LE capture",
            )
        vad_model = "silero" if settings.vad_model is None else settings.vad_model
        if vad_model != "silero":
            raise AudioInputConfigurationError(
                field="vad_model",
                reason="must be silero",
            )
        configured_device = settings.device.strip() if settings.device is not None else ""
        if require_device and configured_device in {"", "default"}:
            raise AudioInputConfigurationError(
                field="device",
                reason="must name an OS loopback or virtual input device",
            )
        device = "default" if not configured_device else configured_device
        return cls(
            source=source,
            device=device,
            silence_timeout=(
                DEFAULT_SILENCE_TIMEOUT
                if settings.silence_timeout is None
                else settings.silence_timeout
            ),
            vad_threshold=(
                DEFAULT_VAD_THRESHOLD
                if settings.vad_threshold is None
                else settings.vad_threshold
            ),
            interrupt_on_vad=(
                True if settings.interrupt_on_vad is None else settings.interrupt_on_vad
            ),
        )


@dataclass(frozen=True, slots=True)
class AudioInputIdentity:
    name: str
    payload_source: str
    config: AudioInputConfig


class SileroModel(Protocol):
    def speech_probability(self, samples: bytes, sample_rate: int) -> float: ...


class VoiceActivityDetector(Protocol):
    def is_speech(self, samples: bytes) -> bool: ...


class PcmBuffer(Protocol):
    def __bytes__(self) -> bytes: ...


class CaptureTimeInfo(Protocol):
    pass


class CaptureStatus(Protocol):
    pass


class CaptureCallback(Protocol):
    def __call__(
        self,
        samples: PcmBuffer,
        frames: int,
        time_info: CaptureTimeInfo,
        status: CaptureStatus,
    ) -> None: ...


class CaptureStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class CaptureFactory(Protocol):
    def create(
        self,
        config: AudioInputConfig,
        callback: CaptureCallback,
    ) -> CaptureStream: ...


class SileroVad:
    def __init__(self, model: SileroModel, *, threshold: float) -> None:
        if not 0 <= threshold <= 1:
            raise AudioInputConfigurationError(
                field="vad_threshold",
                reason="must be between 0 and 1",
            )
        self._model = model
        self._threshold = threshold

    def is_speech(self, samples: bytes) -> bool:
        score = self._model.speech_probability(samples, SAMPLE_RATE)
        if not 0 <= score <= 1:
            raise AudioInputConfigurationError(
                field="silero_score",
                reason="must be between 0 and 1",
            )
        return score >= self._threshold


class CallbackQueue:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise AudioInputConfigurationError(
                field="callback_queue_capacity",
                reason="must be positive",
            )
        self._queue: Queue[bytes] = Queue(maxsize=capacity)
        self._dropped_frames = 0
        self._rejected_frames = 0

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def rejected_frames(self) -> int:
        return self._rejected_frames

    def offer(self, samples: bytes) -> bool:
        if not samples or len(samples) % SAMPLE_WIDTH_BYTES:
            self._rejected_frames += 1
            return False
        try:
            self._queue.put_nowait(samples)
        except Full:
            self._dropped_frames += 1
            return False
        return True

    def pop(self) -> bytes | None:
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

    def clear(self) -> None:
        while self.pop() is not None:
            continue


@dataclass(frozen=True, slots=True)
class SegmentUpdate:
    voice_started: bool
    samples: bytes | None


class VadSegmenter:
    def __init__(self, silence_timeout: float) -> None:
        self._silence_timeout_ms = silence_timeout * 1_000
        self._chunks: list[bytes] = []
        self._silence_ms = 0.0
        self._recording = False

    def consume(self, samples: bytes, *, speech: bool) -> SegmentUpdate:
        duration_ms = len(samples) / (SAMPLE_WIDTH_BYTES * CHANNELS * SAMPLE_RATE) * 1_000
        if speech:
            voice_started = not self._recording
            self._recording = True
            self._silence_ms = 0.0
            self._chunks.append(samples)
            return SegmentUpdate(voice_started=voice_started, samples=None)
        if not self._recording:
            return SegmentUpdate(voice_started=False, samples=None)
        self._chunks.append(samples)
        self._silence_ms += duration_ms
        if self._silence_ms < self._silence_timeout_ms:
            return SegmentUpdate(voice_started=False, samples=None)
        completed = b"".join(self._chunks)
        self.reset()
        return SegmentUpdate(voice_started=False, samples=completed)

    def reset(self) -> None:
        self._chunks.clear()
        self._silence_ms = 0.0
        self._recording = False


def duration_ms(samples: bytes) -> float:
    return len(samples) / (SAMPLE_WIDTH_BYTES * CHANNELS * SAMPLE_RATE) * 1_000
