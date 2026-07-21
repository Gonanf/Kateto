from __future__ import annotations

from asyncio import (  # noqa: ANYIO_OK
    AbstractEventLoop,
    CancelledError,
    Event,
    Task,
    create_task,
    current_task,
    get_running_loop,
    to_thread,
)
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from kateto.core.event import AudioData, AudioInputStatus, AudioInputStatusData, AudioOutput
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager

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
        super().__init__(identity.name)
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
        self._loop = None

    async def on_audio_output(self, data: AudioOutput) -> None:
        self.set_playback_active(not data.final)

    def set_playback_active(self, active: bool) -> None:
        self._playback_active = active

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
                speech = await to_thread(self._vad.is_speech, samples)
                update = self._segmenter.consume(samples, speech=speech)
                if update.voice_started:
                    await self._set_recording(True)
                    await self._interrupt_playback()
                if update.samples is not None:
                    await self._set_recording(False)
                    await self._emit_segment(update.samples)
            self._queue_ready.clear()
            if self._callback_queue.pending:
                self._queue_ready.set()

    async def _interrupt_playback(self) -> None:
        if not self._config.interrupt_on_vad:
            return
        self._playback_active = False
        await self._require_manager().interrupt(
            reason="voice_activity",
            source=self._event_source,
        )

    async def _emit_segment(self, samples: bytes) -> None:
        started_at = monotonic()
        await self._require_manager().emit(
            "audio_chunk",
            AudioData(
                samples=samples,
                sample_rate=16_000,
                channels=1,
                format=PCM_FORMAT,
                source=self._payload_source,
                duration_ms=duration_ms(samples),
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
