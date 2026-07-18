from __future__ import annotations

from collections.abc import Callable

import numpy as np
import sounddevice

from .base import (
    CHANNELS,
    SAMPLE_RATE,
    AudioDeviceError,
    AudioInputConfig,
    CaptureFactory,
)


class SoundDeviceCapture:
    def __init__(self, stream: sounddevice.RawInputStream, config: AudioInputConfig) -> None:
        self._stream = stream
        self._config = config

    def start(self) -> None:
        try:
            self._stream.start()
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioDeviceError(
                source=self._config.source,
                device=self._config.device,
                reason=f"{error}; select an installed input device",
            ) from error

    def stop(self) -> None:
        self._stream.stop()

    def close(self) -> None:
        self._stream.close()


def _resample_pcm(data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample s16le PCM from *from_rate* Hz to *to_rate* Hz."""
    if from_rate == to_rate:
        return data
    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    ratio = from_rate / to_rate
    out_len = int(round(len(pcm) / ratio))
    if out_len == len(pcm):
        return data
    x_old = np.arange(len(pcm))
    x_new = np.linspace(0, len(pcm) - 1, out_len)
    return np.interp(x_new, x_old, pcm).astype(np.int16).tobytes()


def _with_resample(callback: Callable, from_rate: int) -> Callable:
    """Wrap *callback* to resample incoming PCM from *from_rate* to SAMPLE_RATE.

    Buffers resampled audio until at least one VAD window (512 samples /
    1024 bytes) is available, so the model never receives a chunk padded
    mostly with zeros.

    ponytail: without buffering, a 384-frame callback at 44100 Hz resamples
    to 139 samples — well below the 512-sample VAD window.  The resulting
    373 zero-padded samples drown out the real audio and the model returns
    near-zero probability for every chunk.
    """
    to_rate = SAMPLE_RATE
    _buffer = bytearray()
    MIN_BYTES = 512 * 2

    if from_rate == to_rate:
        return callback

    def wrapped(
        samples: bytes,
        frames: int,
        time_source: object,
        status: object,
    ) -> None:
        nonlocal _buffer
        if status:
            callback(samples, frames, time_source, status)
            return
        _buffer.extend(_resample_pcm(bytes(samples), from_rate, to_rate))
        while len(_buffer) >= MIN_BYTES:
            frame = bytes(_buffer[:MIN_BYTES])
            _buffer = _buffer[MIN_BYTES:]
            new_frames = MIN_BYTES // 2
            callback(frame, new_frames, time_source, status)

    return wrapped


class SoundDeviceCaptureFactory(CaptureFactory):
    def create(
        self,
        config: AudioInputConfig,
        callback: Callable,
    ) -> SoundDeviceCapture:
        device = None if config.device == "default" else config.device
        self._validate_device(device, config)
        native_rate = _native_input_rate(device)
        cb = _with_resample(callback, native_rate)
        try:
            stream = sounddevice.RawInputStream(
                device=device,
                samplerate=native_rate,
                channels=CHANNELS,
                dtype="int16",
                callback=cb,
            )
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioDeviceError(
                source=config.source,
                device=config.device,
                reason=f"{error}; select an installed input device",
            ) from error
        return SoundDeviceCapture(stream=stream, config=config)

    @staticmethod
    def _validate_device(device: str | None, config: AudioInputConfig) -> None:
        if device is None:
            return
        try:
            info = sounddevice.query_devices(device=device, kind="input")
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioDeviceError(
                source=config.source,
                device=config.device,
                reason=f"device not found ({error}); select an installed input device",
            ) from error
        if info["max_input_channels"] < 1:
            raise AudioDeviceError(
                source=config.source,
                device=config.device,
                reason="device has no input channels; select a microphone or input device",
            )


def _native_input_rate(device: str | None) -> int:
    """Return the native/default sample rate of *device*."""
    info = sounddevice.query_devices(device=device, kind="input")
    return int(info["default_samplerate"])
