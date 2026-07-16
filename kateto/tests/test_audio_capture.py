from __future__ import annotations

import pytest
import sounddevice

from kateto.plugins.audio_input.base import (
    AudioDeviceError,
    AudioInputConfig,
    CaptureCallback,
    CaptureStatus,
    CaptureTimeInfo,
    PcmBuffer,
)
from kateto.plugins.audio_input.capture import SoundDeviceCaptureFactory


class FixturePortAudioError(ValueError):
    pass


class FixtureRawStream:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


def fixture_config(device: str) -> AudioInputConfig:
    return AudioInputConfig(
        source="audio_input_meet",
        device=device,
        silence_timeout=0.2,
        vad_threshold=0.5,
        interrupt_on_vad=True,
    )


def no_op_capture_callback(
    samples: PcmBuffer,
    frames: int,
    time_info: CaptureTimeInfo,
    status: CaptureStatus,
) -> None:
    del samples, frames, time_info, status


def test_sounddevice_capture_uses_raw_int16_mono_16khz_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a fake RawInputStream constructor that captures its requested format.
    captures: list[tuple[str | None, int, int, str]] = []

    def create_stream(
        *,
        device: str | None,
        samplerate: int,
        channels: int,
        dtype: str,
        callback: CaptureCallback,
    ) -> FixtureRawStream:
        assert callable(callback)
        captures.append((device, samplerate, channels, dtype))
        return FixtureRawStream()

    monkeypatch.setattr(sounddevice, "RawInputStream", create_stream)

    # When: a default microphone capture stream is constructed.
    stream = SoundDeviceCaptureFactory().create(fixture_config("default"), no_op_capture_callback)

    # Then: PortAudio receives raw int16 mono capture at exactly 16 kHz.
    assert captures == [(None, 16_000, 1, "int16")]
    stream.close()


def test_sounddevice_missing_device_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: PortAudio rejects the configured loopback device before capture begins.
    def reject_stream(
        *,
        device: str | None,
        samplerate: int,
        channels: int,
        dtype: str,
        callback: CaptureCallback,
    ) -> FixtureRawStream:
        del device, samplerate, channels, dtype, callback
        raise FixturePortAudioError("invalid device")

    monkeypatch.setattr(sounddevice, "RawInputStream", reject_stream)

    # When: Meet capture requests an unavailable configured device.
    with pytest.raises(AudioDeviceError, match="missing.*installed input device"):
        SoundDeviceCaptureFactory().create(fixture_config("missing"), no_op_capture_callback)

    # Then: startup has no stream object that could leave a capture task running.
