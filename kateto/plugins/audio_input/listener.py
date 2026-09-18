from __future__ import annotations

from asyncio import (  # noqa: ANYIO_OK
    AbstractEventLoop,
    CancelledError,
    Event,
    Task,
    create_task,
    current_task,
    get_running_loop,
    sleep,
    to_thread,
)
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from kateto.core.event import AudioData, AudioInputStatus, AudioInputStatusData, AudioOutput
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.core.rms import apply_ema, calculate_raw_rms

from loguru import logger as log

from .base import (
    PCM_FORMAT,
    AudioDeviceError,
    AudioInputIdentity,
    AudioInputLifecycleError,
    CallbackQueue,
    CaptureFactory,
    SileroVad,
    VadSegmenter,
    duration_ms,
)


class AudioInputPlugin(Plugin):
    def __init__(
        self,
        identity: AudioInputIdentity,
        vad: SileroVad,
        capture_factory: CaptureFactory,
    ) -> None:
        depts = (identity.config.dept,) if identity.config.dept else ()
        super().__init__(identity.name, depts=depts)
        self._payload_source = identity.payload_source
        self._event_source = f"{identity.name}/{identity.payload_source}"
        self._config = identity.config
        self._vad = vad
        self._capture_factory = capture_factory
        self._callback_queue = CallbackQueue(capacity=self._config.callback_queue_capacity)
        self._queue_ready = Event()
        self._resumed_listening = Event()
        self._segmenter = VadSegmenter(identity.config.silence_timeout)
        self._capture: object | None = None
        self._capture_task: Task[None] | None = None
        self._loop: AbstractEventLoop | None = None
        self._capture_session = 0
        self._accepting_audio = False
        self._playback_active = False
        self._playback_started_at: float | None = None
        self._last_playback_chunk_at: float | None = None
        self._deferred_barge_in = False
        self._playback_rms = 0.0
        self._speech_onset_at: float | None = None
        self._turn_buffer = bytearray()
        self._turn_flush_task: Task[None] | None = None
        self._recording_status_emitted = False
        self._recording = False
        self._last_resume_gap_ms: float | None = None

    @property
    def capture_task(self) -> Task[None] | None:
        return self._capture_task

    @property
    def resumed_listening(self) -> Event:
        return self._resumed_listening

    @property
    def last_resume_gap_ms(self) -> float | None:
        return self._last_resume_gap_ms

    async def initialize(self) -> None:
        self._require_manager().register_event("audio_chunk", AudioData)
        self._require_manager().register_event("audio_input_status", AudioInputStatusData)

    async def enable(self) -> None:
        self._callback_queue.clear()
        self._queue_ready.clear()
        self._resumed_listening.clear()
        self._segmenter.reset()
        self._recording = False
        self._recording_status_emitted = False
        self._last_resume_gap_ms = None
        self._playback_started_at = None
        self._last_playback_chunk_at = None
        self._deferred_barge_in = False
        self._playback_rms = 0.0
        self._speech_onset_at = None
        self._cancel_turn_flush()
        self._turn_buffer.clear()
        self._capture_session += 1
        session = self._capture_session
        self._loop = get_running_loop()
        capture = self._capture_factory.create(
            self._config,
            self._callback_for(session),
        )
        self._capture = capture
        self._accepting_audio = True
        try:
            capture.start()
        except AudioDeviceError:
            self._accepting_audio = False
            self._capture = None
            capture.close()
            raise
        self._capture_task = create_task(
            self._drain_callback_queue(),
            name=f"kateto-audio-capture-{self.name}",
        )
        await self._set_recording(False)

    async def disable(self) -> None:
        self._accepting_audio = False
        self._capture_session += 1
        capture = self._capture
        self._capture = None
        capture_task = self._capture_task
        self._capture_task = None
        if capture is not None:
            capture.stop()
            capture.close()
        if capture_task is not None and capture_task is not current_task():
            capture_task.cancel()
            with suppress(CancelledError):
                await capture_task
        self._callback_queue.clear()
        self._queue_ready.clear()
        self._segmenter.reset()
        await self._set_recording(False)
        self._playback_active = False
        self._playback_started_at = None
        self._last_playback_chunk_at = None
        self._deferred_barge_in = False
        self._playback_rms = 0.0
        self._speech_onset_at = None
        self._cancel_turn_flush()
        self._turn_buffer.clear()
        self._loop = None

    async def on_audio_output(self, data: AudioOutput) -> None:
        if data.samples:
            self._playback_rms = apply_ema(calculate_raw_rms(data.samples), self._playback_rms)
            self._last_playback_chunk_at = monotonic()
        self.set_playback_active(not data.final)

    def set_playback_active(self, active: bool) -> None:
        if active:
            if self._playback_active:
                return
            self._playback_active = True
            self._playback_started_at = monotonic()
            if self._last_playback_chunk_at is None:
                self._last_playback_chunk_at = self._playback_started_at
            self._playback_rms = 0.0
        else:
            self._playback_active = False
            self._playback_started_at = None
            self._last_playback_chunk_at = None
            self._deferred_barge_in = False
            self._playback_rms = 0.0
            self._speech_onset_at = None

    def _refresh_playback_idle(self) -> None:
        if not self._playback_active:
            return
        # ponytail: 0 disables the watchdog (documented default comment in
        # base.py); without this guard 0 would expire on the first frame.
        if self._config.playback_idle_timeout <= 0:
            return
        last = self._last_playback_chunk_at
        if last is None:
            return
        if (monotonic() - last) >= self._config.playback_idle_timeout:
            log.info("[mic] playback idle timeout ({:.1f}s without audio_output), reopening mic", self._config.playback_idle_timeout)
            self.set_playback_active(False)

    def _callback_for(self, session: int) -> Callable:
        def callback(
            samples: bytes,
            frames: int,
            time_info: object,
            status: object,
        ) -> None:
            if status:
                return
            self._enqueue_callback(session=session, samples=bytes(samples))

        return callback

    def _enqueue_callback(self, *, session: int, samples: bytes) -> None:
        if not self._accepting_audio or session != self._capture_session:
            return
        if not self._callback_queue.offer(samples):
            return
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._queue_ready.set)
        except RuntimeError:
            return

    async def _drain_callback_queue(self) -> None:
        while True:
            await self._queue_ready.wait()
            while True:
                samples = self._callback_queue.pop()
                if samples is None:
                    break
                self._refresh_playback_idle()
                speech = await to_thread(self._vad.is_speech, samples)
                mic_rms = calculate_raw_rms(samples)
                update = self._segmenter.consume(samples, speech=speech)
                if not speech:
                    self._speech_onset_at = None
                if update.voice_started:
                    log.info("[mic] Speech detected, recording...")
                    await self._set_recording(True)
                    await self._interrupt_playback(mic_rms)
                elif speech and self._playback_active:
                    # Speech continues while our own voice is out: re-check every
                    # frame so a real barge-in fires as soon as it qualifies.
                    await self._interrupt_playback(mic_rms)
                if update.samples is not None:
                    await self._set_recording(False)
                    await self._handle_closed_segment(update.samples)
            self._queue_ready.clear()
            if self._callback_queue.pending:
                self._queue_ready.set()

    async def _interrupt_playback(self, mic_rms: float) -> None:
        if not self._config.interrupt_on_vad:
            return
        if not self._playback_active:
            self._speech_onset_at = None
            await self._require_manager().interrupt(
                reason="voice_activity",
                source=self._event_source,
                dept=self._config.dept,
            )
            return
        now = monotonic()
        started_at = self._playback_started_at
        if started_at is None:
            # ponytail: defensive — playback active without a start stamp.
            started_at = now
            self._playback_started_at = started_at
        grace_ms = self._config.barge_in_grace_ms
        elapsed_ms = (now - started_at) * 1_000
        if elapsed_ms < grace_ms:
            self._deferred_barge_in = True
            self._speech_onset_at = None
            log.info(
                "[mic] vad ignored: own playback within grace ({elapsed:.0f}ms < {grace:.0f}ms), barge-in deferred",
                elapsed=elapsed_ms,
                grace=grace_ms,
            )
            return
        factor = self._config.barge_in_level_factor
        playback_rms = self._playback_rms
        if mic_rms < playback_rms * factor:
            self._deferred_barge_in = True
            self._speech_onset_at = None
            log.info(
                "[mic] barge-in denied mic_rms={mic:.3f} playback_rms={pb:.3f} factor={f} reason=bleed elapsed_ms={el:.0f}",
                mic=mic_rms,
                pb=playback_rms,
                f=factor,
                el=elapsed_ms,
            )
            return
        if self._speech_onset_at is None:
            self._speech_onset_at = now
        sustained_ms = (now - self._speech_onset_at) * 1_000
        required_ms = self._config.barge_in_min_speech_ms
        if sustained_ms < required_ms:
            self._deferred_barge_in = True
            log.info(
                "[mic] barge-in denied mic_rms={mic:.3f} playback_rms={pb:.3f} factor={f} reason=too-short sustained_ms={s:.0f} required_ms={r:.0f}",
                mic=mic_rms,
                pb=playback_rms,
                f=factor,
                s=sustained_ms,
                r=required_ms,
            )
            return
        self._deferred_barge_in = False
        self._speech_onset_at = None
        log.info(
            "[mic] barge-in granted mic_rms={mic:.3f} playback_rms={pb:.3f} factor={f} sustained_ms={s:.0f} elapsed_ms={el:.0f}",
            mic=mic_rms,
            pb=playback_rms,
            f=factor,
            s=sustained_ms,
            el=elapsed_ms,
        )
        self._playback_active = False
        self._playback_started_at = None
        self._playback_rms = 0.0
        await self._require_manager().interrupt(
            reason="voice_activity",
            source=self._event_source,
            dept=self._config.dept,
        )

    async def _handle_closed_segment(self, samples: bytes) -> None:
        self._refresh_playback_idle()
        if self._playback_active:
            log.info("[mic] segment attributed to own playback, dropped")
            return
        is_new_turn = not self._turn_buffer
        self._turn_buffer.extend(samples)
        if is_new_turn and not self._config.interrupt_on_vad:
            await self._require_manager().interrupt(
                reason="user_turn",
                source=self._event_source,
                dept=self._config.dept,
            )
        if duration_ms(bytes(self._turn_buffer)) >= self._config.max_turn_secs * 1_000:
            self._cancel_turn_flush()
            await self._flush_turn()
            return
        self._rearm_turn_flush()

    def _rearm_turn_flush(self) -> None:
        self._cancel_turn_flush()
        if not self._turn_buffer:
            return
        self._turn_flush_task = create_task(
            self._turn_flush_later(),
            name=f"kateto-audio-turn-{self.name}",
        )

    def _cancel_turn_flush(self) -> None:
        task = self._turn_flush_task
        self._turn_flush_task = None
        if task is not None and task is not current_task():
            task.cancel()

    async def _turn_flush_later(self) -> None:
        try:
            await sleep(self._config.turn_silence_timeout)
        except CancelledError:
            return
        if self._turn_flush_task is not current_task():
            return
        self._turn_flush_task = None
        await self._flush_turn()

    async def _flush_turn(self) -> None:
        if not self._turn_buffer:
            return
        await self._emit_segment(bytes(self._turn_buffer))
        self._turn_buffer.clear()

    async def _emit_segment(self, samples: bytes) -> None:
        dur = duration_ms(samples)
        log.info("[mic] Captured utterance: {:.2f}s ({:.0f}ms), sending to Whisper...", dur / 1000.0, dur)
        started_at = monotonic()
        await self._require_manager().emit(
            "audio_chunk",
            AudioData(
                samples=samples,
                sample_rate=16_000,
                channels=1,
                format=PCM_FORMAT,
                source=self._payload_source,
                duration_ms=dur,
            ),
            source=self._event_source,
        )
        self._last_resume_gap_ms = (monotonic() - started_at) * 1_000
        self._resumed_listening.set()

    async def _set_recording(self, recording: bool) -> None:
        if self._recording_status_emitted and self._recording == recording:
            return
        self._recording = recording
        self._recording_status_emitted = True
        await self._require_manager().emit(
            "audio_input_status",
            AudioInputStatusData(
                status=AudioInputStatus.RECORDING if recording else AudioInputStatus.IDLE,
            ),
            source=self._event_source,
        )

    def _require_manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            raise AudioInputLifecycleError(plugin=self.name)
        return manager
