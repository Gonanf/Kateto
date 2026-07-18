from __future__ import annotations

from typing import override

import sounddevice

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, InterruptData
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager

from .base import AudioOutputDeviceError, AudioOutputFormatError, PCM_S16LE


class SoundDeviceOutputStream:
    _stream: sounddevice.RawOutputStream
    _device: str | None

    def __init__(self, stream: sounddevice.RawOutputStream, *, device: str | None) -> None:
        self._stream = stream
        self._device = device

    @override
    def start(self) -> None:
        try:
            self._stream.start()
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioOutputDeviceError(device=self._device, reason=str(error)) from error

    @override
    def stop(self) -> None:
        self._stream.stop()

    @override
    def close(self) -> None:
        self._stream.close()

    @override
    def write(self, data: bytes) -> object:
        try:
            return self._stream.write(data)
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioOutputDeviceError(device=self._device, reason=str(error)) from error


class SoundDeviceOutputFactory:
    @override
    def create(
        self,
        *,
        device: str | None,
        sample_rate: int,
        channels: int,
    ) -> SoundDeviceOutputStream:
        try:
            stream = sounddevice.RawOutputStream(
                device=device,
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
            )
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioOutputDeviceError(device=device, reason=str(error)) from error
        return SoundDeviceOutputStream(stream, device=device)


class AudioOutputPlayer(Plugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        player_factory: SoundDeviceOutputFactory | None = None,
    ) -> None:
        super().__init__("audio_output_player")
        self._device: str | None = _configured_device(settings)
        self._factory: SoundDeviceOutputFactory = SoundDeviceOutputFactory() if player_factory is None else player_factory
        self._stream: SoundDeviceOutputStream | None = None
        self._stream_format: tuple[int, int] | None = None
        self._playing = False
        self._status_emitted = False

    @override
    async def initialize(self) -> None:
        self._manager().register_event("audio_output", AudioOutput)
        self._manager().register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def enable(self) -> None:
        await self._set_playing(False)

    @override
    async def disable(self) -> None:
        self._close_stream()
        await self._set_playing(False)

    async def on_audio_output(self, data: AudioOutput) -> None:
        _validate_pcm(data)
        if data.final:
            self._close_stream()
            await self._set_playing(False)
            return
        if not data.samples:
            return
        stream = await self._stream_for(data)
        _ = stream.write(data.samples)

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self._close_stream()
        await self._set_playing(False)

    async def _stream_for(self, data: AudioOutput) -> SoundDeviceOutputStream:
        requested_format = (data.sample_rate, data.channels)
        stream = self._stream
        if stream is not None and self._stream_format != requested_format:
            self._close_stream()
            await self._set_playing(False)
            stream = None
        if stream is None:
            stream = self._factory.create(
                device=self._device,
                sample_rate=data.sample_rate,
                channels=data.channels,
            )
            stream.start()
            self._stream = stream
            self._stream_format = requested_format
            await self._set_playing(True)
        return stream

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        self._stream_format = None
        if stream is not None:
            stream.stop()
            stream.close()

    async def _set_playing(self, playing: bool) -> None:
        if self._status_emitted and self._playing == playing:
            return
        self._playing = playing
        self._status_emitted = True
        await self._manager().emit(
            "audio_output_status",
            AudioOutputStatusData(
                status=AudioOutputStatus.PLAYING if playing else AudioOutputStatus.IDLE,
            ),
            source=self.name,
        )

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = "audio_output_player must be enabled before use"
            raise RuntimeError(msg)
        return manager


def _configured_device(settings: PluginSettings) -> str | None:
    device = settings.device.strip() if settings.device is not None else ""
    return None if device in {"", "default"} else device


def _validate_pcm(data: AudioOutput) -> None:
    if data.format != PCM_S16LE:
        raise AudioOutputFormatError(format=data.format, reason="must be PCM s16LE")
    frame_width = data.channels * 2
    if len(data.samples) % frame_width:
        raise AudioOutputFormatError(format=data.format, reason="contains an incomplete PCM sample frame")
