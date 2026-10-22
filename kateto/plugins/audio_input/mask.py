"""Audio input fed by the mask's WebSocket stream.

The `/ws/mask` handler only has to call
`get_mask_capture_factory().push(pcm, voice=<voice_id>)`; the capture, VAD,
segmentation, turn accumulation and barge-in are the same machinery every other
`AudioInputPlugin` uses.

The requested voice travels in the event payload (`AudioData.voice`), NOT in
`envelope.target`: `PluginManager._resolve_subscribers` filters by `target`, so
an `audio_chunk` targeted at "doktor" would never reach the ASR and the
pipeline would go mute. The voice is resolved later, at generation time.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from kateto.core.config import PluginSettings

from .base import (
    AudioInputConfig,
    AudioInputConfigurationError,
    AudioInputIdentity,
    AudioInputLifecycleError,
    CaptureFactory,
    SileroVad,
)
from .listener import AudioInputPlugin

MASK_SAMPLE_RATE: Final = 16_000
MASK_CHANNELS: Final = 1
MASK_FORMAT: Final = "pcm_s16le"


class MaskCapture:
    """Capture without a device: frames arrive by feed() from the WebSocket."""

    def __init__(self, callback: Callable[[bytes, int, None, None], None]) -> None:
        self._callback = callback
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def close(self) -> None:
        self._started = False

    def feed(self, samples: bytes) -> None:
        if self._started:
            self._callback(samples, len(samples) // 2, None, None)


class MaskCaptureFactory:
    """Owns the active MaskCapture and is the push entry point for the WS."""

    def __init__(self) -> None:
        self._capture: MaskCapture | None = None
        self._voice: str | None = None

    def create(
        self,
        config: AudioInputConfig,
        callback: Callable[[bytes, int, None, None], None],
    ) -> MaskCapture:
        capture = MaskCapture(callback)
        self._capture = capture
        return capture

    def push(
        self,
        samples: bytes,
        *,
        sample_rate: int = MASK_SAMPLE_RATE,
        channels: int = MASK_CHANNELS,
        format: str = MASK_FORMAT,
        voice: str | None = None,
    ) -> None:
        if sample_rate != MASK_SAMPLE_RATE:
            raise AudioInputConfigurationError(
                field="sample_rate",
                reason=f"must be {MASK_SAMPLE_RATE} Hz for mono PCM s16LE capture",
            )
        if channels != MASK_CHANNELS:
            raise AudioInputConfigurationError(
                field="channels",
                reason="must be 1 for mono PCM s16LE capture",
            )
        if format != MASK_FORMAT:
            raise AudioInputConfigurationError(
                field="format",
                reason=f"must be {MASK_FORMAT}",
            )
        if samples == b"" or len(samples) % 2 != 0:
            raise ValueError("mask audio must be non-empty, even-length PCM s16LE bytes")
        capture = self._capture
        if capture is None:
            raise AudioInputLifecycleError(plugin="audio_input_mask")
        if voice is not None and voice:
            self._voice = voice
        capture.feed(samples)

    @property
    def voice(self) -> str | None:
        return self._voice


class MaskAudioInput(AudioInputPlugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        vad: SileroVad,
        capture_factory: CaptureFactory | None = None,
        whisper_transcriber: object = None,
        classifier_client: object = None,
    ) -> None:
        super().__init__(
            identity=AudioInputIdentity(
                name="audio_input_mask",
                payload_source="mask",
                config=AudioInputConfig.from_settings(
                    settings,
                    source="audio_input_mask",
                    require_device=False,
                ),
            ),
            vad=vad,
            capture_factory=(
                get_mask_capture_factory()
                if capture_factory is None
                else capture_factory
            ),
            whisper_transcriber=whisper_transcriber,
            classifier_client=classifier_client,
        )

    def _route_voice(self) -> str | None:
        return getattr(self._capture_factory, "voice", None)


_MASK_CAPTURE_FACTORY: MaskCaptureFactory | None = None


def get_mask_capture_factory() -> MaskCaptureFactory:
    global _MASK_CAPTURE_FACTORY
    if _MASK_CAPTURE_FACTORY is None:
        _MASK_CAPTURE_FACTORY = MaskCaptureFactory()
    return _MASK_CAPTURE_FACTORY
