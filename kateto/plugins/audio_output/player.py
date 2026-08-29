from __future__ import annotations

import asyncio
import struct
from typing import override

from anyio import to_thread
from pydantic import BaseModel
import sounddevice

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, EventEnvelope, InterruptData
from kateto.core.plugin import EventHandler, Plugin
from kateto.core.rms import RMSProcessor
from kateto.voices.base import AudioPipeline, get_pipeline

from .base import AudioOutputDeviceError, AudioOutputFormatError, PCM_S16LE


class SoundDeviceOutputStream:
    _stream: sounddevice.RawOutputStream
    _device: str | None

    def __init__(self, stream: sounddevice.RawOutputStream, *, device: str | None) -> None:
        self._stream = stream
        self._device = device

    def start(self) -> None:
        try:
            self._stream.start()
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioOutputDeviceError(device=self._device, reason=str(error)) from error

    def stop(self) -> None:
        try:
            self._stream.stop()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._stream.close()
        except Exception:
            pass

    def write(self, data: bytes) -> object:
        try:
            return self._stream.write(data)
        except (sounddevice.PortAudioError, ValueError):
            return None


class SoundDeviceOutputFactory:
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
                latency="high",
                blocksize=2048,
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
        self._playing: bool = False
        self._status_emitted: bool = False
        self._mixer_task: asyncio.Task[None] | None = None
        self._active_pipelines: dict[str, AudioPipeline] = {}
        self._pipeline_queues: dict[str, asyncio.Queue[bytes | None]] = {}
        self._rms_processors: dict[str, RMSProcessor] = {}

    def _rms_for(self, voice_id: str) -> RMSProcessor:
        if voice_id not in self._rms_processors:
            self._rms_processors[voice_id] = RMSProcessor()
        return self._rms_processors[voice_id]

    @override
    async def initialize(self) -> None:
        self.required_manager.register_event("audio_output", AudioOutput)
        self.required_manager.register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def enable(self) -> None:
        await self._set_playing(False)

    @override
    async def disable(self) -> None:
        self._close_stream()
        if self._mixer_task is not None and not self._mixer_task.done():
            self._mixer_task.cancel()
        self._mixer_task = None
        self._active_pipelines.clear()
        self._pipeline_queues.clear()
        await self._set_playing(False)

    async def on_audio_output(self, data: AudioOutput) -> None:
        if data.voice_id is not None:
            pipeline = get_pipeline(data.voice_id)
            if pipeline is not None:
                if data.voice_id not in self._active_pipelines:
                    self._active_pipelines[data.voice_id] = pipeline
                    self._pipeline_queues[data.voice_id] = pipeline.pcm_queue
                    if self._mixer_task is None or self._mixer_task.done():
                        self._mixer_task = asyncio.create_task(
                            self._run_mixer(), name="kateto-mixer"
                        )
                if data.samples:
                    await pipeline.pcm_queue.put(data.samples)
                if data.final:
                    await pipeline.pcm_queue.put(None)
                return
        _validate_pcm(data)
        if data.final:
            self._close_stream()
            await self._set_playing(False)
            return
        if not data.samples:
            return
        stream = await self._stream_for(data)
        # ponytail: chunked write + per-window RMS so the overlay jaw moves
        # continuously for non-streaming TTS (EdgeTTS/Boson); Zonos path uses the mixer.
        processor = self._rms_for(data.voice_id or "")
        window = max(2, int(data.sample_rate * 0.02) * 2)
        for offset in range(0, len(data.samples), window):
            chunk = data.samples[offset : offset + window]
            if not chunk:
                continue
            _ = await to_thread.run_sync(stream.write, chunk)
            if self.manager is not None:
                await self.manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=data.sample_rate,
                        channels=data.channels,
                        format=data.format,
                        voice_id=data.voice_id,
                        rms=processor.process(chunk),
                        text=data.text,
                    ),
                    source=self.name,
                )

    async def _run_mixer(self) -> None:
        try:
            await self._set_playing(True)
            idle_cycles = 0
            while True:
                if not self._pipeline_queues:
                    idle_cycles += 1
                    if idle_cycles > 200:  # ~1.0s grace period between streaming phrases
                        break
                    await asyncio.sleep(0.005)
                    continue
                idle_cycles = 0
                done_voices: list[str] = []
                pcm_buffers: list[bytes] = []
                active_voice_pcms: list[tuple[str, bytes]] = []
                for voice_id, queue in list(self._pipeline_queues.items()):
                    try:
                        pcm = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        continue
                    if pcm is None:
                        done_voices.append(voice_id)
                        continue
                    if pcm:
                        pcm_buffers.append(pcm)
                        active_voice_pcms.append((voice_id, pcm))
                for vid in done_voices:
                    self._pipeline_queues.pop(vid, None)
                    self._active_pipelines.pop(vid, None)
                if pcm_buffers:
                    mixed = _mix_pcm(pcm_buffers)
                    stream = self._open_or_reopen_stream((24_000, 1))
                    _ = await to_thread.run_sync(stream.write, mixed)
                    if self.manager is not None:
                        for vid, pcm in active_voice_pcms:
                            rms = self._rms_for(vid).process(pcm)
                            await self.manager.emit(
                                "audio_output",
                                AudioOutput(
                                    samples=b"",
                                    sample_rate=24_000,
                                    channels=1,
                                    format=PCM_S16LE,
                                    voice_id=vid,
                                    rms=rms,
                                ),
                                source=self.name,
                            )
                else:
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            pass
        finally:
            self._active_pipelines.clear()
            self._pipeline_queues.clear()
            await self._set_playing(False)

    @override
    async def _enqueue(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        if self.enabled and envelope.name == "interrupt":
            await handler(envelope.data)
            return
        await super()._enqueue(envelope, handler)

    def _open_or_reopen_stream(self, requested_format: tuple[int, int]) -> SoundDeviceOutputStream:
        stream = self._stream
        if stream is None or self._stream_format != requested_format:
            self._close_stream()
            sample_rate, channels = requested_format
            stream = self._factory.create(
                device=self._device,
                sample_rate=sample_rate,
                channels=channels,
            )
            stream.start()
            self._stream = stream
            self._stream_format = requested_format
            asyncio.create_task(self._set_playing(True))
        return stream

    async def on_interrupt(self, data: InterruptData) -> None:
        manager = self.manager
        target_voices: set[str] | None = None
        if data.dept and manager is not None:
            target_voices = {
                plugin.name
                for plugin in manager.get_plugins()
                if "voice" in plugin.capabilities and data.dept in plugin.depts
            }
        if target_voices is not None:
            for voice_id in list(self._active_pipelines.keys()):
                if voice_id in target_voices:
                    self._active_pipelines.pop(voice_id, None)
                    self._pipeline_queues.pop(voice_id, None)
            if not self._active_pipelines:
                self._close_stream()
                if self._mixer_task is not None and not self._mixer_task.done():
                    self._mixer_task.cancel()
                self._mixer_task = None
                await self._set_playing(False)
        else:
            self._close_stream()
            if self._mixer_task is not None and not self._mixer_task.done():
                self._mixer_task.cancel()
            self._mixer_task = None
            self._active_pipelines.clear()
            self._pipeline_queues.clear()
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
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    async def _set_playing(self, playing: bool) -> None:
        if self.manager is None:
            self._playing = playing
            return
        if self._status_emitted and self._playing == playing:
            return
        self._playing = playing
        self._status_emitted = True
        _ = await self.manager.emit(
            "audio_output_status",
            AudioOutputStatusData(
                status=AudioOutputStatus.PLAYING if playing else AudioOutputStatus.IDLE,
            ),
            source=self.name,
        )


def _configured_device(settings: PluginSettings) -> str | None:
    device = settings.device.strip() if settings.device is not None else ""
    return None if device in {"", "default"} else device


def _validate_pcm(data: AudioOutput) -> None:
    if data.format != PCM_S16LE:
        raise AudioOutputFormatError(format=data.format, reason="must be PCM s16LE")
    frame_width = data.channels * 2
    if len(data.samples) % frame_width:
        raise AudioOutputFormatError(format=data.format, reason="contains an incomplete PCM sample frame")


def _mix_pcm(buffers: list[bytes]) -> bytes:
    """Mix multiple s16LE PCM buffers by averaging samples, with ducking."""
    if len(buffers) == 1:
        return buffers[0]
    max_len = max(len(b) for b in buffers)
    mixed = bytearray(max_len)
    for i in range(0, max_len, 2):
        total = 0
        count = 0
        for buf in buffers:
            if i + 1 < len(buf):
                sample = struct.unpack_from("<h", buf, i)[0]
                total += sample
                count += 1
        if count > 0:
            avg = total // count
            struct.pack_into("<h", mixed, i, max(-32768, min(32767, avg)))
    return bytes(mixed)
