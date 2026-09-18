from __future__ import annotations

import asyncio
import time
from typing import override

from anyio import to_thread
from loguru import logger
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
                blocksize=1024,
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
        # Voice whose lane is CURRENTLY reaching the device (set by the
        # sequencer on every head-lane write). Overlay/transcript consumers
        # use it to sync text with actual audible playback.
        self._playing_speaker: str | None = None
        self._status_emitted: bool = False
        self._mixer_task: asyncio.Task[None] | None = None
        self._active_pipelines: dict[str, AudioPipeline] = {}
        self._pipeline_queues: dict[str, asyncio.Queue[bytes | None]] = {}
        # Raw data lanes for non-streaming TTS (EdgeTTS/Boson/CAMB): same lane
        # model as pipelines so the mixer serializes ALL producers per voice.
        # Lanes are per-SENTENCE (voice#N): a sentence synthesized while the
        # previous one still plays opens a new lane queued behind it. Sharing
        # one lane per voice orphaned the next sentence's already-queued chunks
        # when the previous sentence's final sentinel popped the lane.
        self._raw_lanes: dict[str, asyncio.Queue[bytes | None]] = {}
        self._raw_formats: dict[str, tuple[int, int]] = {}
        self._lane_voice: dict[str, str] = {}
        self._voice_lane: dict[str, str] = {}
        self._lane_gen: dict[str, int] = {}
        self._closed_lanes: set[str] = set()
        self._rms_processors: dict[str, RMSProcessor] = {}
        self._last_write_time: float = 0.0
        # PCM bytes written to the device per lane since the lane started.
        # Lets viseme consumers map energy to sentence-relative playback time.
        self._lane_bytes: dict[str, int] = {}

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
        self._raw_lanes.clear()
        self._raw_formats.clear()
        self._lane_bytes.clear()
        self._lane_voice.clear()
        self._voice_lane.clear()
        self._lane_gen.clear()
        self._closed_lanes.clear()
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
                    self._lane_voice[data.voice_id] = data.voice_id
                    self._lane_bytes[data.voice_id] = 0
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
        key = data.voice_id or ""
        if data.final:
            # Final chunk closes this voice's CURRENT raw data lane: the
            # sequencer advances to the next lane when the sentinel drains.
            lane_key = self._voice_lane.get(key, key)
            logger.info("[player] final voice={} lane={} seq={}", data.voice_id, lane_key, data.sequence)
            lane = self._raw_lanes.get(lane_key)
            if lane is not None:
                self._closed_lanes.add(lane_key)
                await lane.put(None)
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
        # Data lane model: every producer gets its own FIFO lane; the mixer
        # serializes lanes in arrival order (no mixing, no overlap). A speak
        # event that arrives while another lane is still yielding simply opens
        # a new lane behind the current one.
        # ponytail: lane maxsize bounds memory if the head lane stalls forever.
        lane_key = self._voice_lane.get(key)
        if lane_key is None or lane_key in self._closed_lanes or lane_key not in self._raw_lanes:
            gen = self._lane_gen.get(key, 0) + 1
            self._lane_gen[key] = gen
            lane_key = key if gen == 1 else f"{key}#{gen}"
            self._voice_lane[key] = lane_key
            self._lane_voice[lane_key] = key
            logger.info("[player] lane open voice={} lane={} seq={}", data.voice_id, lane_key, data.sequence)
            lane = asyncio.Queue(maxsize=64)
            self._raw_lanes[lane_key] = lane
            self._raw_formats[lane_key] = (data.sample_rate, data.channels)
            self._pipeline_queues[lane_key] = lane
            self._lane_bytes[lane_key] = 0
            if self._mixer_task is None or self._mixer_task.done():
                self._mixer_task = asyncio.create_task(
                    self._run_mixer(), name="kateto-mixer"
                )
        lane = self._raw_lanes[lane_key]
        logger.info(
            "[player] queued voice={} lane={} seq={} bytes={} lane_size={}",
            data.voice_id, lane_key, data.sequence, len(data.samples), lane.qsize(),
        )
        await lane.put(data.samples)

    async def _run_mixer(self) -> None:
        """Lane sequencer: drains one voice's data lane at a time, in arrival order.

        Lanes are never mixed — a speak event that arrives while another lane is
        still yielding is queued behind it, so overlapping generations never
        produce overlapping speech. The `None` sentinel marks a lane as
        finished ("stopped yielding") and advances playback to the next one.
        """
        try:
            await self._set_playing(True)
            idle_cycles = 0
            head_empty_since: float | None = None
            while True:
                if not self._pipeline_queues:
                    idle_cycles += 1
                    if idle_cycles > 200:  # ~1.0s grace period between streaming phrases
                        break
                    head_empty_since = None
                    await asyncio.sleep(0.005)
                    continue
                idle_cycles = 0
                head_id = next(iter(self._pipeline_queues.keys()))
                # An empty head lane must not wedge lanes behind it (a lost
                # final would otherwise mute everything for 10s): drain the
                # first lane that actually has data. Same-voice order is still
                # FIFO per lane; only a head awaiting late data can be jumped,
                # which beats a decade of silence. The 10s drop below remains
                # the backstop for permanently dead lanes.
                voice_id: str | None = None
                pcm: bytes | None = b""
                for candidate_id, candidate_queue in self._pipeline_queues.items():
                    try:
                        pcm = candidate_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        continue
                    voice_id = candidate_id
                    break
                if voice_id is None:
                    # Head lane has not yielded yet (synthesis in flight): wait
                    # for it, but drop a dead lane so it cannot block the device.
                    now = time.monotonic()
                    if head_empty_since is None:
                        head_empty_since = now
                    elif (now - head_empty_since) > 10.0:
                        logger.warning(
                            "audio_output_player: lane {} stalled >10s; dropping", head_id
                        )
                        self._pop_lane(head_id)
                        head_empty_since = None
                    elif self._stream is not None and (now - self._last_write_time) > 1.5:
                        # Idle timeout: close stream to prevent ALSA xrun
                        self._close_stream()
                    await asyncio.sleep(0.005)
                    continue
                head_empty_since = None
                if pcm is None:
                    # Lane stopped yielding: pop it and advance to the next lane.
                    logger.info("[player] lane done lane={} voice={} played_bytes={}", voice_id, self._lane_voice.get(voice_id, voice_id), self._lane_bytes.get(voice_id, 0))
                    self._pop_lane(voice_id)
                    self._rms_for(voice_id).reset()
                    continue
                if pcm:
                    fmt = self._raw_formats.get(voice_id, (24_000, 1))
                    audio_ms: float | None = None
                    try:
                        stream = self._open_or_reopen_stream(fmt)
                        _ = await to_thread.run_sync(stream.write, pcm)
                        self._last_write_time = time.monotonic()
                        sample_rate, channels = fmt
                        played = self._lane_bytes.get(voice_id, 0) + len(pcm)
                        self._lane_bytes[voice_id] = played
                        audio_ms = played / (sample_rate * channels * 2) * 1000.0
                        logger.info(
                            "[player] played lane={} voice={} bytes={} audio_ms={:.0f}",
                            voice_id, self._lane_voice.get(voice_id, voice_id), len(pcm), audio_ms,
                        )
                    except (
                        sounddevice.PortAudioError,
                        ValueError,
                        AudioOutputDeviceError,
                    ) as error:
                        # Host error (e.g. PaErrorCode -9999 "Unanticipated host
                        # error"): the stream is dead, not the sequencer. Drop
                        # this chunk, close the corrupted stream, and let the
                        # next iteration reopen a fresh one. Never let the
                        # exception escape — a dead sequencer task silently
                        # kills all output.
                        logger.warning(
                            "audio_output_player: device write failed ({}); "
                            "reopening stream", error,
                        )
                        self._close_stream()
                        self._last_write_time = time.monotonic()
                        await self._set_playing(False)
                        await asyncio.sleep(0.05)
                    rms = self._rms_for(voice_id).process(pcm)
                    heard_voice = self._lane_voice.get(voice_id, voice_id)
                    if self._playing_speaker != heard_voice:
                        # New lane reached the device: this voice is now the
                        # one actually being heard.
                        self._playing_speaker = heard_voice
                    await self._send_viseme(heard_voice, rms, None, audio_ms=audio_ms)
                else:
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            pass
        except Exception as error:  # pragma: no cover - defensive
            # Last-resort guard: a sequencer task that dies with an unretrieved
            # exception leaves the bus up but audio permanently silent.
            logger.exception("audio_output_player: mixer crashed: {}", error)
        finally:
            self._active_pipelines.clear()
            self._pipeline_queues.clear()
            self._raw_lanes.clear()
            self._raw_formats.clear()
            self._lane_bytes.clear()
            self._lane_voice.clear()
            self._voice_lane.clear()
            self._lane_gen.clear()
            self._closed_lanes.clear()
            await self._set_playing(False)

    def _pop_lane(self, voice_id: str, *, rescue: bool = True) -> None:
        queue = self._pipeline_queues.pop(voice_id, None)
        self._active_pipelines.pop(voice_id, None)
        self._lane_bytes.pop(voice_id, None)
        self._raw_lanes.pop(voice_id, None)
        fmt = self._raw_formats.pop(voice_id, (24_000, 1))
        voice = self._lane_voice.pop(voice_id, voice_id)
        self._closed_lanes.discard(voice_id)
        for name, lane_key in list(self._voice_lane.items()):
            if lane_key == voice_id:
                del self._voice_lane[name]
        if rescue and queue is not None:
            # A popped lane can still hold unplayed chunks of the NEXT sentence
            # (synthesis outruns realtime playback on the shared pipeline queue,
            # or the voice replaced the queue object). Re-queue them behind as a
            # fresh lane instead of orphaning them into silence.
            rest: list[bytes | None] = []
            while True:
                try:
                    rest.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            if any(item is not None for item in rest):
                gen = self._lane_gen.get(voice, 0) + 1
                self._lane_gen[voice] = gen
                rescued_key = voice if gen == 1 else f"{voice}#{gen}"
                rescued: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
                for item in rest:
                    rescued.put_nowait(item)
                self._raw_lanes[rescued_key] = rescued
                self._raw_formats[rescued_key] = fmt
                self._pipeline_queues[rescued_key] = rescued
                self._lane_bytes[rescued_key] = 0
                self._lane_voice[rescued_key] = voice
                logger.info(
                    "[player] lane rescue lane={} voice={} chunks={}",
                    rescued_key, voice, len(rest),
                )

    @override
    async def _enqueue(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        if self.enabled and envelope.name == "interrupt":
            await handler(envelope.data)
            return
        await super()._enqueue(envelope, handler)

    def _open_or_reopen_stream(self, requested_format: tuple[int, int]) -> SoundDeviceOutputStream:
        stream = self._stream
        if stream is None or self._stream_format != requested_format:
            logger.info(
                "[player] stream open rate={} channels={} (was={})",
                requested_format[0], requested_format[1], self._stream_format,
            )
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
        logger.info("[player] interrupt reason={} dept={}", data.reason, data.dept)
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
            for lane_key in list(self._pipeline_queues.keys()):
                if self._lane_voice.get(lane_key, lane_key) in target_voices:
                    # Barge-in drops, never rescues: the user took the floor.
                    self._pop_lane(lane_key, rescue=False)
            if not self._pipeline_queues:
                self._playing_speaker = None
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
            self._raw_lanes.clear()
            self._raw_formats.clear()
            self._lane_bytes.clear()
            self._lane_voice.clear()
            self._voice_lane.clear()
            self._lane_gen.clear()
            self._closed_lanes.clear()
            self._playing_speaker = None
            await self._set_playing(False)
            self._idle_event.set()

    def _close_stream(self, *, abort: bool = False) -> None:
        stream = self._stream
        self._stream = None
        self._stream_format = None
        if stream is not None:
            logger.info("[player] stream close abort={}", abort)
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
        self,
        voice_id: str | None,
        rms: float,
        text: str | None = None,
        *,
        audio_ms: float | None = None,
    ) -> None:
        if self.manager is None:
            return
        vo = self.manager.get_plugin("visual_overlay")
        if vo is not None and hasattr(vo, "update_viseme"):
            try:
                await vo.update_viseme(voice_id, rms, text, audio_ms=audio_ms)
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
