import io
import json
import re
import unicodedata
import wave
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
    wait_for,
)
from collections.abc import Callable
from contextlib import suppress
from time import monotonic

from pathlib import Path
from typing import Any, Final

import httpx

from kateto.core.event import (
    AudioData,
    AudioInputStatus,
    AudioInputStatusData,
    AudioOutput,
    TranscriptionData,
)
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


def _normalize_text(text: str) -> str:
    # ponytail: normalize text strips accents, punctuation, repeated letters, and case.
    nfkd = unicodedata.normalize("NFKD", text)
    unaccented = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = unaccented.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    normalized_words = [re.sub(r"([a-z])\1{2,}", r"\1\1", w) for w in cleaned.split()]
    return " ".join(normalized_words)


_GATE_FILLERS: Final[frozenset[str]] = frozenset({
    "umm", "emm", "mmm", "mm", "eh", "ah", "oh", "un", "uno", "una", "o", "u", "um", "em",
})

_GATE_PYWHISPER_PROVIDERS: dict[str, Any] = {}


def _is_filler_or_noise(word: str) -> bool:
    return len(word) <= 1 or word in _GATE_FILLERS


def evaluate_gate_lexical(
    text: str,
    ignore_words: set[str],
) -> tuple[bool, str, list[str]]:
    """Evaluates text against the tolerant lexical gate matcher.

    1. Normalizar: minusculas, sacar tildes, sacar puntuacion, colapsar espacios.
    2. Descartar rellenos y ruido: `umm emm mmm mm eh ah oh un uno una o u` y cualquier token de 1 caracter.
    3. Si no queda nada -> IGNORE (era puro relleno).
    4. Si queda algo: todas las palabras restantes tienen que estar en el lexico
       (`interrupt_gate_ignore_words`) y ser <= 3 -> IGNORE; cualquier otra cosa -> INTERRUPT.
    5. Retorna (is_ignore, norm_text, remaining_words).
    """
    norm_text = _normalize_text(text)
    words = norm_text.split()
    remaining = [w for w in words if not _is_filler_or_noise(w)]
    if not remaining:
        return True, norm_text, remaining

    all_in_lexicon = all(w in ignore_words for w in remaining)
    word_count_ok = (len(remaining) <= 3) or (len(set(remaining)) <= 3)
    return (all_in_lexicon and word_count_ok), norm_text, remaining


def _pcm_to_wav_bytes(samples: bytes, sample_rate: int = 16_000, channels: int = 1) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(samples)
        return buffer.getvalue()


class AudioInputPlugin(Plugin):
    def __init__(
        self,
        identity: AudioInputIdentity,
        vad: SileroVad,
        capture_factory: CaptureFactory,
        *,
        whisper_transcriber: object = None,
        classifier_client: object = None,
    ) -> None:
        depts = (identity.config.dept,) if identity.config.dept else ()
        super().__init__(identity.name, depts=depts)
        self._payload_source = identity.payload_source
        self._event_source = f"{identity.name}/{identity.payload_source}"
        self._config = identity.config
        self._vad = vad
        self._capture_factory = capture_factory
        self._whisper_transcriber = whisper_transcriber
        self._classifier_client = classifier_client
        self._http_client: httpx.AsyncClient | None = None
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
        self._turn_segments = 0
        self._turn_flush_task: Task[None] | None = None
        self._recording_status_emitted = False
        self._recording = False
        self._last_resume_gap_ms: float | None = None

        # Semantic interrupt gate state
        self._gate_buffer = bytearray()
        self._gate_task: Task[None] | None = None
        self._gate_frame_event = Event()
        self._gate_speech_active = False
        self._gate_discard_current = False
        self._ignore_phrase_set = {
            _normalize_text(w)
            for w in self._config.interrupt_gate_ignore_words
            if _normalize_text(w)
        }
        self._ignore_word_set = {
            word for phrase in self._ignore_phrase_set for word in phrase.split()
        }
        self._gate_backend_warning_logged = False

    @property
    def capture_task(self) -> Task[None] | None:
        return self._capture_task

    @property
    def gate_task(self) -> Task[None] | None:
        return self._gate_task

    @property
    def turn_buffer(self) -> bytes:
        return bytes(self._turn_buffer)

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
        self._turn_segments = 0
        self._gate_buffer.clear()
        self._gate_speech_active = False
        self._gate_discard_current = False
        self._gate_frame_event.clear()
        if self._gate_task is not None and not self._gate_task.done():
            self._gate_task.cancel()
        self._gate_task = None
        if self._http_client is None:
            self._http_client = httpx.AsyncClient()
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
        if self._gate_task is not None and self._gate_task is not current_task():
            self._gate_task.cancel()
            with suppress(CancelledError):
                await self._gate_task
        self._gate_task = None
        self._gate_buffer.clear()
        self._gate_discard_current = False
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
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
        self._turn_segments = 0
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
            if self._gate_task is not None and not self._gate_task.done():
                self._gate_task.cancel()
                self._gate_task = None

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
                    self._gate_buffer.clear()
                    self._gate_discard_current = False
                    self._gate_speech_active = True
                    self._gate_buffer.extend(samples)
                    self._gate_frame_event.set()
                    await self._set_recording(True)
                    await self._interrupt_playback(mic_rms)
                else:
                    if self._segmenter._recording:
                        self._gate_speech_active = speech
                        self._gate_buffer.extend(samples)
                        self._gate_frame_event.set()
                    if speech and self._playback_active:
                        # Speech continues while our own voice is out: re-check every
                        # frame so a real barge-in fires as soon as it qualifies.
                        await self._interrupt_playback(mic_rms)
                if speech and not self._playback_active and self._turn_flush_task is not None:
                    self._cancel_turn_flush()
                    log.info("[mic] turn flush cancelled: user resumed speaking")
                if update.samples is not None:
                    self._gate_speech_active = False
                    self._gate_frame_event.set()
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

        # Acoustic qualification passed
        if self._config.interrupt_gate == "off":
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
            return

        # Semantic gate is active ("lexical" | "classifier")
        if self._gate_task is not None and not self._gate_task.done():
            return
        self._gate_discard_current = False
        self._gate_task = create_task(
            self._evaluate_gate(),
            name=f"kateto-gate-{self.name}",
        )

    async def _evaluate_gate(self) -> None:
        gate_start = monotonic()
        timeout_s = self._config.interrupt_gate_timeout_ms / 1000.0
        window_ms = self._config.interrupt_gate_window_ms
        required_min_speech_ms = self._config.barge_in_min_speech_ms

        while True:
            elapsed = monotonic() - gate_start
            if elapsed >= timeout_s:
                break
            dur = duration_ms(bytes(self._gate_buffer))
            if dur >= window_ms:
                break
            if not self._gate_speech_active and dur >= required_min_speech_ms:
                break
            remaining = timeout_s - elapsed
            if remaining <= 0:
                break
            self._gate_frame_event.clear()
            try:
                await wait_for(self._gate_frame_event.wait(), timeout=min(remaining, 0.04))
            except TimeoutError:
                pass

        total_elapsed = monotonic() - gate_start
        if total_elapsed >= timeout_s:
            log.warning(
                "[mic] gate verdict=INTERRUPT in {:.0f}ms (timeout reached: limit={:.0f}ms)",
                total_elapsed * 1000,
                self._config.interrupt_gate_timeout_ms,
            )
            await self._execute_gate_interrupt(reason="voice_activity")
            return

        samples = bytes(self._gate_buffer)
        if not samples:
            await self._execute_gate_interrupt(reason="voice_activity")
            return

        t_asr_start = monotonic()
        asr_text = ""
        asr_failed = False
        remaining_asr = timeout_s - (monotonic() - gate_start)
        if remaining_asr <= 0:
            asr_failed = True
        else:
            try:
                transcription = await wait_for(
                    self._transcribe_gate_samples(samples),
                    timeout=remaining_asr,
                )
                if transcription and transcription.text:
                    asr_text = transcription.text
            except Exception as err:
                if not self._gate_backend_warning_logged:
                    log.warning("[mic] gate ASR error: {}", err)
                asr_failed = True

        asr_ms = (monotonic() - t_asr_start) * 1000

        if asr_failed or (monotonic() - gate_start) >= timeout_s:
            log.warning(
                "[mic] gate verdict=INTERRUPT in {:.0f}ms (asr_failed={})",
                (monotonic() - gate_start) * 1000,
                asr_failed,
            )
            await self._execute_gate_interrupt(reason="voice_activity")
            return

        is_lexical_ignore, norm_text, remaining_words = evaluate_gate_lexical(
            asr_text, self._ignore_word_set
        )

        cls_ms = 0.0
        verdict = "INTERRUPT"

        if self._config.interrupt_gate == "lexical":
            verdict = "IGNORE" if is_lexical_ignore else "INTERRUPT"
        elif self._config.interrupt_gate == "classifier":
            if is_lexical_ignore:
                verdict = "IGNORE"
            else:
                t_cls_start = monotonic()
                cls_failed = False
                cat = "EXECUTE"
                conf = 0.0
                remaining_cls = timeout_s - (monotonic() - gate_start)
                if remaining_cls <= 0:
                    cls_failed = True
                else:
                    try:
                        cat, conf = await wait_for(
                            self._classify_gate_text(norm_text or asr_text),
                            timeout=remaining_cls,
                        )
                    except Exception as err:
                        log.warning("[mic] gate classifier error: {}", err)
                        cls_failed = True
                cls_ms = (monotonic() - t_cls_start) * 1000

                if not cls_failed and cat.startswith("IGNORE_") and conf >= self._config.interrupt_gate_min_confidence:
                    verdict = "IGNORE"
                else:
                    verdict = "INTERRUPT"

        total_ms = (monotonic() - gate_start) * 1000
        log.info(
            "[mic] gate verdict={} in {:.0f}ms (asr={:.0f}ms cls={:.0f}ms) raw={!r} norm={!r}",
            verdict,
            total_ms,
            asr_ms,
            cls_ms,
            asr_text,
            norm_text,
        )

        if verdict == "IGNORE":
            self._gate_discard_current = True
        else:
            self._gate_discard_current = False
            await self._execute_gate_interrupt(reason="voice_activity")

    async def _execute_gate_interrupt(self, *, reason: str = "voice_activity") -> None:
        self._deferred_barge_in = False
        self._speech_onset_at = None
        self._playback_active = False
        self._playback_started_at = None
        self._playback_rms = 0.0
        self._gate_discard_current = False
        await self._require_manager().interrupt(
            reason=reason,
            source=self._event_source,
            dept=self._config.dept,
        )

    async def _transcribe_gate_samples(self, samples: bytes) -> TranscriptionData:
        backend = self._config.interrupt_gate_backend

        if backend == "pywhispercpp":
            model_path = self._config.interrupt_gate_model
            if not model_path:
                if not self._gate_backend_warning_logged:
                    log.warning("[mic] interrupt gate backend 'pywhispercpp' configured without interrupt_gate_model, falling back to interrupt")
                    self._gate_backend_warning_logged = True
                raise RuntimeError("interrupt_gate_model not configured")

            if not Path(model_path).is_file():
                if not self._gate_backend_warning_logged:
                    log.warning("[mic] interrupt gate model file not found: {!r}, falling back to interrupt", model_path)
                    self._gate_backend_warning_logged = True
                raise RuntimeError(f"interrupt gate model not found: {model_path}")

            from kateto.providers.whisper import PyWhisperCppProvider
            if model_path not in _GATE_PYWHISPER_PROVIDERS:
                lang = getattr(self._config, "language", None) or "es"
                provider = PyWhisperCppProvider(
                    model=model_path,
                    n_threads=4,
                    language=lang,
                )
                await provider._ensure_initialized()
                _GATE_PYWHISPER_PROVIDERS[model_path] = provider
            else:
                provider = _GATE_PYWHISPER_PROVIDERS[model_path]

            audio = AudioData(
                samples=samples,
                sample_rate=16_000,
                channels=1,
                format=PCM_FORMAT,
                source="gate",
                duration_ms=duration_ms(samples),
            )
            return await provider.transcribe(audio)

        if backend == "server":
            endpoint = self._config.interrupt_gate_endpoint.rstrip("/")
            if not endpoint:
                if not self._gate_backend_warning_logged:
                    log.warning("[mic] interrupt gate backend 'server' configured without interrupt_gate_endpoint, falling back to interrupt")
                    self._gate_backend_warning_logged = True
                raise RuntimeError("interrupt_gate_endpoint not configured")

            wav_bytes = _pcm_to_wav_bytes(samples, sample_rate=16_000, channels=1)

            client = self._http_client
            close_client = False
            if client is None or client.is_closed:
                client = httpx.AsyncClient()
                close_client = True

            url = f"{endpoint}/inference"
            try:
                data = {
                    "response_format": "json",
                    "temperature": "0.0",
                    "language": getattr(self._config, "language", None) or "es",
                }
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                resp = await client.post(
                    url,
                    data=data,
                    files=files,
                    timeout=self._config.interrupt_gate_timeout_ms / 1000.0,
                )
                resp.raise_for_status()
                res_json = resp.json()
                return TranscriptionData(text=res_json.get("text", ""))
            except Exception as err:
                if not self._gate_backend_warning_logged:
                    log.warning("[mic] whisper-server gate endpoint {!r} error: {}, falling back to interrupt", url, err)
                    self._gate_backend_warning_logged = True
                raise
            finally:
                if close_client:
                    await client.aclose()

        # backend == "same":
        transcriber = self._whisper_transcriber
        if transcriber is None and self.manager is not None:
            transcriber = self.manager.get_plugin("audio_processor_whisper")
        if transcriber is None:
            if not self._gate_backend_warning_logged:
                log.warning("[mic] no whisper transcriber available, falling back to interrupt")
                self._gate_backend_warning_logged = True
            raise RuntimeError("no whisper transcriber available")
        if hasattr(transcriber, "transcribe_samples"):
            return await transcriber.transcribe_samples(samples)
        if hasattr(transcriber, "transcribe"):
            try:
                audio = AudioData(
                    samples=samples,
                    sample_rate=16_000,
                    channels=1,
                    format=PCM_FORMAT,
                    source="gate",
                    duration_ms=duration_ms(samples),
                )
                return await transcriber.transcribe(audio)
            except TypeError:
                res = await transcriber.transcribe(samples)
                if isinstance(res, str):
                    return TranscriptionData(text=res)
                return res
        if callable(transcriber):
            res = transcriber(samples)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, str):
                return TranscriptionData(text=res)
            return res
        raise RuntimeError(f"unsupported whisper transcriber: {transcriber}")

    async def _classify_gate_text(self, text: str) -> tuple[str, float]:
        if self._classifier_client is not None:
            client = self._classifier_client
            if hasattr(client, "classify"):
                res = await client.classify(text)
                if hasattr(res, "category") and hasattr(res, "confidence"):
                    cat = res.category.value if hasattr(res.category, "value") else str(res.category)
                    return cat, float(res.confidence if res.confidence is not None else 1.0)
                if isinstance(res, tuple):
                    return str(res[0]), float(res[1])
            if callable(client):
                res = client(text)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, tuple):
                    return str(res[0]), float(res[1])
                if hasattr(res, "category"):
                    cat = res.category.value if hasattr(res.category, "value") else str(res.category)
                    return cat, float(res.confidence if res.confidence is not None else 1.0)

        url = self._config.interrupt_gate_classifier_url.rstrip("/")
        if not url.endswith("/v1/chat/completions"):
            url = f"{url}/v1/chat/completions"

        http_client = self._http_client
        close_client = False
        if http_client is None:
            http_client = httpx.AsyncClient()
            close_client = True

        try:
            payload = {
                "model": "classifier",
                "messages": [
                    {"role": "system", "content": "classify intent"},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.0,
                "stream": False,
                "response_format": {"type": "json_object"},
            }
            resp = await http_client.post(url, json=payload, timeout=2.0)
            resp.raise_for_status()
            data = resp.json()
            completion = data["choices"][0]["message"]["content"]
            parsed = json.loads(completion)
            cat = str(parsed.get("category", "EXECUTE"))
            conf = float(parsed.get("confidence", 0.0))
            return cat, conf
        finally:
            if close_client:
                await http_client.aclose()

    async def _handle_closed_segment(self, samples: bytes) -> None:
        self._refresh_playback_idle()
        if self._gate_discard_current:
            self._gate_discard_current = False
            log.info("[mic] segment discarded by semantic gate (ignored backchannel)")
            return
        if self._playback_active:
            log.info("[mic] segment attributed to own playback, dropped")
            return
        is_new_turn = not self._turn_buffer
        self._turn_buffer.extend(samples)
        self._turn_segments += 1
        if is_new_turn and not self._config.interrupt_on_vad:
            await self._require_manager().interrupt(
                reason="user_turn",
                source=self._event_source,
                dept=self._config.dept,
            )
        if duration_ms(bytes(self._turn_buffer)) >= self._config.max_turn_secs * 1_000:
            self._cancel_turn_flush()
            await self._flush_turn(reason="max_turn")
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
            hold_ms = self._config.turn_hold_ms
            if hold_ms > 0:
                await sleep(hold_ms / 1_000.0)
        except CancelledError:
            return
        if self._turn_flush_task is not current_task():
            return
        self._turn_flush_task = None
        await self._flush_turn(reason="silence")

    async def _flush_turn(self, *, reason: str = "silence") -> None:
        if not self._turn_buffer:
            return
        segments = self._turn_segments
        buffered_ms = int(duration_ms(bytes(self._turn_buffer)))
        log.info(f"[mic] turn flush reason={reason} segments={segments} buffered_ms={buffered_ms}")
        await self._emit_segment(bytes(self._turn_buffer))
        self._turn_buffer.clear()
        self._turn_segments = 0

    def _route_voice(self) -> str | None:
        """Voz pedida por la fuente de audio, si la fuente puede pedir una (mask)."""
        return None

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
                voice=self._route_voice(),
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
