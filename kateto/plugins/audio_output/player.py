from __future__ import annotations

import asyncio
import struct
import time
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

    @property
    def active(self) -> bool:
        return getattr(self._stream, "active", False)

    def start(self) -> None:
        try:
            if not self.active:
                self._stream.start()
        except (sounddevice.PortAudioError, ValueError) as error:
            raise AudioOutputDeviceError(device=self._device, reason=str(error)) from error

    def stop(self) -> None:
        try:
            self._stream.stop()
        except Exception:
            pass

    def abort(self) -> None:
        try:
            self._stream.abort()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._stream.close()
        except Exception:
            pass

    def write(self, data: bytes) -> object:
        try:
            if not self.active:
                self.start()
            return self._stream.write(data)
        except (sounddevice.PortAudioError, ValueError):
            try:
                self._stream.stop()
            except Exception:
                pass
            raise


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
        self._interrupted: bool = False
        self._interrupted_at: float = 0.0
        self._current_speaker: str | None = None
        self._interrupted_voice: str | None = None
        self._status_emitted: bool = False
        self._mixer_task: asyncio.Task[None] | None = None
        self._active_pipelines: dict[str, AudioPipeline] = {}
        self._pipeline_queues: dict[str, asyncio.Queue[bytes | None]] = {}
        self._rms_processors: dict[str, RMSProcessor] = {}
        self._last_write_time: float = 0.0

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

    @property
    @override
    def is_busy(self) -> bool:
        if super().is_busy:
            return True
        if self._playing:
            return True
        if self._active_pipelines or self._pipeline_queues:
            return True
        return False

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
            self._interrupted = False
            self._interrupted_voice = None
            if not self.is_busy:
                self._idle_event.set()
            return
        if not data.samples:
            return
        now = time.monotonic()
        if self._interrupted:
            if data.voice_id and data.voice_id == self._interrupted_voice and (now - self._interrupted_at < 2.5):
                return
            self._interrupted = False
            self._interrupted_voice = None
        self._current_speaker = data.voice_id
        stream = await self._stream_for(data)
        # ponytail: chunked write + per-window RMS so the overlay jaw moves
        # continuously for non-streaming TTS (EdgeTTS/Boson); Zonos path uses the mixer.
        processor = self._rms_for(data.voice_id or "")
        window = max(2, int(data.sample_rate * 0.02) * 2)
        for offset in range(0, len(data.samples), window):
            if self._interrupted or self._stream is None:
                break
            chunk = data.samples[offset : offset + window]
            if not chunk:
                continue
            try:
                _ = await to_thread.run_sync(stream.write, chunk)
                self._last_write_time = time.monotonic()
            except Exception:
                # ponytail: never abort() on write failure — stream may be in
                # xrun-corrupted state where abort() triggers double-free in
                # PortAudio's ALSA mmap path. Graceful stop+close+reopen.
                self._close_stream()
                stream = await self._stream_for(data)
                try:
                    _ = await to_thread.run_sync(stream.write, chunk)
                    self._last_write_time = time.monotonic()
                except Exception:
                    break
            if self._interrupted or self._stream is None:
                break
            await self._send_viseme(data.voice_id, processor.process(chunk), data.text)

        if self._interrupted:
            self._close_stream()
            await self._set_playing(False)
            self._interrupted = False
            self._interrupted_voice = None

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
                    self._last_write_time = time.monotonic()
                    for vid, pcm in active_voice_pcms:
                        rms = self._rms_for(vid).process(pcm)
                        await self._send_viseme(vid, rms, None)
                else:
                    # Idle timeout: close stream after 1.5s of no data to prevent ALSA xrun
                    if self._stream is not None and (time.monotonic() - self._last_write_time) > 1.5:
                        self._close_stream()
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
        self._interrupted = True
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
            self._interrupted = True
            self._interrupted_at = time.monotonic()
            self._interrupted_voice = self._current_speaker
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except Exception:
                    break
            # Graceful stop+close (never abort — see _close_stream)
            self._close_stream()
            if self._mixer_task is not None and not self._mixer_task.done():
                self._mixer_task.cancel()
            self._mixer_task = None
            self._active_pipelines.clear()
            self._pipeline_queues.clear()
            await self._set_playing(False)
            self._idle_event.set()

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
        else:
            stream.start()
        await self._set_playing(True)
        return stream

    def _close_stream(self, *, abort: bool = False) -> None:
        stream = self._stream
        self._stream = None
        self._stream_format = None
        if stream is not None:
            # ponytail: never call abort() — on xrun-corrupted streams, abort()
            # triggers double-free in PortAudio's ALSA mmap path. Use graceful
            # stop() + close() even when abort was requested.
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
            if not playing and not self.is_busy:
                self._idle_event.set()
            elif playing:
                self._idle_event.clear()
            return
        if self._status_emitted and self._playing == playing:
            return
        self._playing = playing
        if not playing and not self.is_busy:
            self._idle_event.set()
        elif playing:
            self._idle_event.clear()
        self._status_emitted = True
        _ = await self.manager.emit(
            "audio_output_status",
            AudioOutputStatusData(
                status=AudioOutputStatus.PLAYING if playing else AudioOutputStatus.IDLE,
            ),
            source=self.name,
        )

    async def _send_viseme(
        self, voice_id: str | None, rms: float, text: str | None = None
    ) -> None:
        if self.manager is None:
            return
        vo = self.manager.get_plugin("visual_overlay")
        if vo is not None and hasattr(vo, "update_viseme"):
            try:
                await vo.update_viseme(voice_id, rms, text)
            except Exception:
                pass


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
