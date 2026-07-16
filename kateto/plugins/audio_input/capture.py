from __future__ import annotations

from typing import Protocol

import sounddevice

from .base import (
    CHANNELS,
    SAMPLE_RATE,
    AudioDeviceError,
    AudioInputConfig,
    CaptureCallback,
    CaptureFactory,
    CaptureStream,
)


class RawInputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class SoundDeviceCapture:
    def __init__(self, stream: RawInputStream, config: AudioInputConfig) -> None:
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


class SoundDeviceCaptureFactory(CaptureFactory):
    def create(
        self,
        config: AudioInputConfig,
        callback: CaptureCallback,
    ) -> CaptureStream:
        device = None if config.device == "default" else config.device
        self._validate_device(device, config)
        try:
            stream = sounddevice.RawInputStream(
                device=device,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=callback,
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
