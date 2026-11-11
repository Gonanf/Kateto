from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import queue
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, override

import numpy as np
from loguru import logger
from pydantic import BaseModel

from hipotenusa.core.config import PluginConfigRegistry, PluginSettings
from hipotenusa.core.event import (
    AudioOutput,
    AudioOutputStatus,
    AudioOutputStatusData,
    EventEnvelope,
    InterruptData,
    TextChunk,
)
from hipotenusa.core.plugin import EventHandler, Plugin

# phonon-40m-es (gradium) via the `ptts` Rust runtime (PyPI package `ptts`).
# Gated HF repo: the checkpoint resolves in the runtime (HF_TOKEN), not here,
# so `model` accepts an hf:// id (default), a local checkpoint dir, or a
# config.json path. Per-voice speaker names live in each voice's config
# (voice.jane.phonon_voice); the plugin-level default lives in
# [plugin.audio_output_phonon].
PLUGIN_SETTINGS_KEY = "audio_output_phonon"
DEFAULT_MODEL = "hf://gradium/phonon-40m-es"
DEFAULT_LANG = "es"
DEFAULT_QUANT = "q8"
# `auto` elige el backend GPU del wheel; cae a CPU si el wheel es CPU-only.
DEFAULT_DEVICE = "auto"
# phonon streams 80ms frames at 24kHz mono; streams a chunk per frame.
DEFAULT_SAMPLE_RATE = 24_000
FINAL_SENTINEL_SAMPLE_RATE = 24_000

PluginConfigRegistry.register_plugin_param(PLUGIN_SETTINGS_KEY, "default_voice", None)
PluginConfigRegistry.register_plugin_param(PLUGIN_SETTINGS_KEY, "lang", None)
PluginConfigRegistry.register_plugin_param(PLUGIN_SETTINGS_KEY, "quant", None)
PluginConfigRegistry.register_plugin_param(PLUGIN_SETTINGS_KEY, "device", None)
PluginConfigRegistry.register_voice_param("phonon_voice", None)

log = logger


class PhononVoiceNotAvailableError(RuntimeError):
    """ptts is not installed, or the Phonon checkpoint cannot be loaded."""


def _pcm16(chunk: Any) -> bytes:
    """float32 PCM in [-1, 1] -> little-endian int16, the player lane format."""
    samples = np.asarray(chunk, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return b""
    return (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _setting(settings: PluginSettings, key: str) -> Any:
    # Registered params land as model extras; declared fields land as attributes.
    value = getattr(settings, key, None)
    return settings.get(key) if value is None else value


class PhononProvider:
    """Local CPU TTS via the ptts runtime (Rust; no torch).

    The checkpoint loads lazily on first synthesis and stays cached for the
    process. Synthesis runs in a worker thread and yields PCM as ptts decodes
    it (one 80ms frame per chunk; never the full sentence).
    """

    def __init__(self, settings: PluginSettings) -> None:
        self._model = str(_setting(settings, "model") or DEFAULT_MODEL)
        self._lang = str(_setting(settings, "lang") or DEFAULT_LANG)
        self._quant = str(_setting(settings, "quant") or DEFAULT_QUANT)
        self._device = str(_setting(settings, "device") or DEFAULT_DEVICE)
        self._tts: Any | None = None

    @property
    def sample_rate(self) -> int:
        return int(getattr(self._load(), "sample_rate", DEFAULT_SAMPLE_RATE))

    def _load(self) -> Any:
        if self._tts is not None:
            return self._tts
        try:
            import ptts  # noqa: PLC0415
        except ImportError as err:
            raise PhononVoiceNotAvailableError(
                "ptts is not installed; run `pip install 'hipotenusa[phonon]'` "
                "(or `uv add --optional phonon 'ptts>=0.7.0'`) to enable local TTS"
            ) from err
        try:
            self._tts = ptts.TTS(self._model, lang=self._lang, quant=self._quant, device=self._device)
        except Exception as err:
            raise PhononVoiceNotAvailableError(
                f"phonon checkpoint {self._model!r} could not be loaded: {err}. "
                "phonon-40m-* repos are gated: accept the terms on the model page "
                "and set HF_TOKEN (`hf auth login`)"
            ) from err
        return self._tts

    async def stream_sentence(
        self,
        sentence: TextChunk,
        *,
        voice: str | None = None,
    ) -> AsyncIterator[AudioOutput]:
        tts = await asyncio.to_thread(self._load)
        sample_rate = int(getattr(tts, "sample_rate", DEFAULT_SAMPLE_RATE))
        bridge: queue.Queue[bytes | None] = queue.Queue()

        def _synthesize() -> None:
            try:
                # Leaving the with-block stops the stream early and waits for
                # ptts' workers: no half-written frame leaks into the lane.
                with tts.stream(sentence.text, voice=voice) as audio:
                    for chunk in audio:
                        pcm = _pcm16(chunk)
                        if pcm:
                            bridge.put(pcm)
            except Exception as exc:
                log.warning(
                    "[phonon] synthesize failed voice={} chars={}: {}",
                    voice,
                    len(sentence.text),
                    exc,
                )
            finally:
                bridge.put(None)

        worker = asyncio.create_task(asyncio.to_thread(_synthesize))
        seq = 0
        cancelled = False
        try:
            while True:
                pcm = await asyncio.to_thread(bridge.get)
                if pcm is None:
                    break
                yield AudioOutput(
                    samples=pcm,
                    sample_rate=sample_rate,
                    channels=1,
                    format="pcm_s16le",
                    voice_id=voice,
                    sequence=seq,
                    text=sentence.text,
                )
                seq += 1
        except asyncio.CancelledError:
            # ptts cannot be stopped mid-frame from another thread; the worker
            # finishes and its bridge is discarded.
            # ponytail: background synth tail on interrupt, add a ptts stop token if latency matters.
            cancelled = True
            raise
        finally:
            await worker
        if cancelled:
            return
        yield AudioOutput(
            samples=b"",
            sample_rate=sample_rate,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=seq,
            final=True,
            text=sentence.text,
        )


class PhononTTSAudioOutput(Plugin):
    """Local CPU TTS via phonon-40m-es + ptts.

    Mirrors PiperTTSAudioOutput: streams PCM chunk-by-chunk as ptts decodes it
    (no full-sentence wait) and emits into the player lane at 24kHz mono.
    """

    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: PhononProvider | None = None,
        voice_map: Mapping[str, Mapping[str, str]] | None = None,
        default_voice: str | None = None,
    ) -> None:
        super().__init__(PLUGIN_SETTINGS_KEY)
        self._provider: PhononProvider = PhononProvider(settings) if provider is None else provider
        self._settings = settings
        self._voice_map: dict[str, dict[str, str]] = {
            str(k).casefold(): dict(v) for k, v in (voice_map or {}).items()
        }
        self._default_voice: str | None = default_voice or _setting(settings, "default_voice") or None
        self._interrupted: bool = False
        self._interrupted_voice: str | None = None
        self._interrupted_at: float = 0.0
        self._current_voice: str | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._playing = False
        self._status_emitted = False

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("audio_output", AudioOutput)
        manager.register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def _enqueue(
        self, envelope: EventEnvelope[BaseModel], handler: EventHandler
    ) -> None:
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case _:
                await super()._enqueue(envelope, handler)

    async def on_text_chunk(self, data: TextChunk) -> None:
        if data.voice_id is None:
            return

        now = time.monotonic()
        if self._interrupted:
            if (
                data.voice_id == self._interrupted_voice
                and data.sequence > 0
                and (now - self._interrupted_at < 2.5)
            ):
                return
            self._interrupted = False
            self._interrupted_voice = None

        self._current_voice = data.voice_id

        raw_text = (data.text or "").strip()
        if not raw_text:
            # Chunk final sin texto = fin de turno: centinela para que el
            # cliente cierre el turno.
            if data.final and self.required_manager is not None:
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=FINAL_SENTINEL_SAMPLE_RATE,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=data.voice_id,
                        sequence=0,
                        final=True,
                        text="",
                    ),
                    source=self.name,
                )
            return

        task = asyncio.create_task(self._emit_pcm(data), name=f"hipotenusa-phonon-{data.voice_id}")
        self._stream_task = task
        try:
            await task
        except asyncio.CancelledError:
            if not self._interrupted:
                raise
        finally:
            if self._stream_task is task:
                self._stream_task = None
            await self._set_playing(False)
            if not self.is_busy:
                self._idle_event.set()

    @property
    @override
    def is_busy(self) -> bool:
        if super().is_busy:
            return True
        return self._stream_task is not None and not self._stream_task.done()

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        log.info("[phonon] interrupt voice={}", self._current_voice)
        self._interrupted = True
        self._interrupted_voice = self._current_voice
        self._interrupted_at = time.monotonic()
        await self._cancel_stream()
        retained: list = []
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                self.queue.task_done()
                env, _ = item
                chunk_vid = getattr(env.data, "voice_id", None)
                if chunk_vid is not None and chunk_vid != self._interrupted_voice:
                    retained.append(item)
            except Exception:
                break
        for item in retained:
            await self.queue.put(item)
        await self._set_playing(False)
        self._idle_event.set()

    async def _emit_pcm(self, data: TextChunk) -> None:
        raw_text = (data.text or "").strip()
        if not raw_text:
            return
        if self._interrupted and data.voice_id == self._interrupted_voice:
            return
        voice_id_str = data.voice_id
        if voice_id_str is None:
            return
        voice_config = self._voice_map.get(str(voice_id_str).casefold(), {})
        phonon_voice: str | None = voice_config.get("phonon_voice") or self._default_voice
        await self._set_playing(True)
        log.info(
            "[phonon] synth start voice={} phonon_voice={} chars={} text={!r}",
            data.voice_id, phonon_voice or "default", len(raw_text), raw_text[:80],
        )
        try:
            out_sample_rate = FINAL_SENTINEL_SAMPLE_RATE
            out_channels = 1
            out_format = "pcm_s16le"
            seq = 0
            pcm_chunk = bytearray()
            CHUNK_THRESHOLD = 16384

            async for output in self._provider.stream_sentence(
                data,
                voice=phonon_voice,
            ):
                if self._interrupted and data.voice_id == self._interrupted_voice:
                    break
                out_sample_rate = output.sample_rate
                out_channels = output.channels
                out_format = output.format
                if output.samples:
                    pcm_chunk.extend(output.samples)
                    if len(pcm_chunk) >= CHUNK_THRESHOLD:
                        if self.required_manager is not None:
                            log.info(
                                "[phonon] emit voice={} seq={} bytes={}",
                                data.voice_id, seq, len(pcm_chunk),
                            )
                            _ = await self.required_manager.emit(
                                "audio_output",
                                AudioOutput(
                                    samples=bytes(pcm_chunk),
                                    sample_rate=out_sample_rate,
                                    channels=out_channels,
                                    format=out_format,
                                    voice_id=data.voice_id,
                                    sequence=seq,
                                    final=False,
                                    text=data.text,
                                ),
                                source=self.name,
                            )
                            seq += 1
                        pcm_chunk.clear()

            stopped = self._interrupted and data.voice_id == self._interrupted_voice
            if stopped:
                log.info("[phonon] synth interrupted voice={} seq={}", data.voice_id, seq)

            if not stopped and pcm_chunk and self.required_manager is not None:
                log.info(
                    "[phonon] emit tail voice={} seq={} bytes={}",
                    data.voice_id, seq, len(pcm_chunk),
                )
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=bytes(pcm_chunk),
                        sample_rate=out_sample_rate,
                        channels=out_channels,
                        format=out_format,
                        voice_id=data.voice_id,
                        sequence=seq,
                        final=bool(data.final),
                        text=data.text,
                    ),
                    source=self.name,
                )
                seq += 1
                pcm_chunk.clear()

            if data.final and not stopped and self.required_manager is not None:
                log.info("[phonon] emit final voice={} seq={}", data.voice_id, seq)
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=out_sample_rate,
                        channels=out_channels,
                        format=out_format,
                        voice_id=data.voice_id,
                        sequence=seq,
                        final=True,
                        text=data.text,
                    ),
                    source=self.name,
                )
        except PhononVoiceNotAvailableError as exc:
            # Dependency missing or checkpoint unavailable: log a clear error,
            # close the player lane, and keep the runtime alive.
            log.error("[phonon] {} (voice={})", exc, data.voice_id)
            if self.required_manager is not None:
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=FINAL_SENTINEL_SAMPLE_RATE,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=data.voice_id,
                        sequence=0,
                        final=True,
                        text=data.text,
                    ),
                    source=self.name,
                )
        finally:
            await self._set_playing(False)
            if not self.is_busy:
                self._idle_event.set()

    async def _cancel_stream(self) -> None:
        task = self._stream_task
        if task is None or task.done():
            return
        _ = task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._stream_task = None

    async def _set_playing(self, playing: bool) -> None:
        if self._status_emitted and self._playing == playing:
            return
        self._playing = playing
        self._status_emitted = True
        await self.required_manager.emit(
            "audio_output_status",
            AudioOutputStatusData(
                status=AudioOutputStatus.PLAYING if playing else AudioOutputStatus.IDLE,
            ),
            source=self.name,
        )


# Backwards compatibility alias, matching PiperTTSPlugin convention.
PhononTTSPlugin = PhononTTSAudioOutput
