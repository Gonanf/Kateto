from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import time
from collections.abc import Mapping
from typing import override

from loguru import logger
from pydantic import BaseModel

from kateto.core.config import PluginConfigRegistry, PluginSettings
from kateto.core.event import (
    AudioOutput,
    AudioOutputStatus,
    AudioOutputStatusData,
    EventEnvelope,
    InterruptData,
    TextChunk,
)
from kateto.core.plugin import EventHandler, Plugin
from kateto.providers.piper import PiperProvider, PiperVoiceNotAvailableError

# Dynamic config parameters contributed by this plugin. Per-voice values live
# in each voice's config (voice.jane.piper_voice, ...); plugin-level fallbacks
# live in [plugin.audio_output_piper].
PluginConfigRegistry.register_plugin_param("audio_output_piper", "default_voice", None)
PluginConfigRegistry.register_plugin_param("audio_output_piper", "download_dir", None)
PluginConfigRegistry.register_plugin_param("audio_output_piper", "length_scale", None)
PluginConfigRegistry.register_plugin_param("audio_output_piper", "speaker_id", None)
PluginConfigRegistry.register_voice_param("piper_voice", None)
PluginConfigRegistry.register_voice_param("piper_length_scale", None)
PluginConfigRegistry.register_voice_param("piper_speaker_id", None)

log = logger


class PiperTTSAudioOutput(Plugin):
    """Local CPU TTS via piper-tts.

    Mirrors EdgeTTSAudioOutput: streams PCM chunk-by-chunk as piper produces
    it (no full-sentence wait) and emits into the player lane.
    """

    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: PiperProvider | None = None,
        voice_map: Mapping[str, Mapping[str, str]] | None = None,
        default_voice: str | None = None,
    ) -> None:
        super().__init__("audio_output_piper")
        self._provider: PiperProvider = PiperProvider(settings) if provider is None else provider
        self._settings = settings
        self._voice_map: dict[str, dict[str, str]] = {
            str(k).casefold(): dict(v) for k, v in (voice_map or {}).items()
        }
        self._default_voice: str = (
            default_voice
            or getattr(settings, "default_voice", None)
            or (settings.get("default_voice") if hasattr(settings, "get") else None)
            or "es_AR-daniela-high"
        )
        self._default_length_scale: float = (
            settings.get("length_scale") if hasattr(settings, "get") and settings.get("length_scale") else 1.0
        )
        self._default_speaker_id: int | None = (
            settings.get("speaker_id") if hasattr(settings, "get") else None
        )
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
            # Chunk final sin texto = fin de turno: se manda el centinela final
            # para que el cliente cierre el turno. Antes se descartaba y el
            # cliente cortaba en el primer final por-chunk (hablaba solo el 1ro).
            if data.final and self.required_manager is not None:
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=22_050,
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

        task = asyncio.create_task(self._emit_pcm(data), name=f"kateto-piper-{data.voice_id}")
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
        if self._stream_task is not None and not self._stream_task.done():
            return True
        return False

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        log.info("[piper] interrupt voice={}", self._current_voice)
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
        raw_voice = voice_config.get("piper_voice")
        piper_voice: str = raw_voice if raw_voice else self._default_voice
        raw_length = voice_config.get("piper_length_scale")
        length_scale = float(raw_length) if raw_length else self._default_length_scale
        raw_speaker = voice_config.get("piper_speaker_id")
        speaker_id = int(raw_speaker) if raw_speaker else self._default_speaker_id
        await self._set_playing(True)
        log.info(
            "[piper] synth start voice={} piper_voice={} length_scale={} chars={} text={!r}",
            data.voice_id, piper_voice, length_scale, len(raw_text), raw_text[:80],
        )
        try:
            out_sample_rate = 22_050
            out_channels = 1
            out_format = "pcm_s16le"
            seq = 0
            pcm_chunk = bytearray()
            CHUNK_THRESHOLD = 16384

            async for output in self._provider.stream_sentence(
                data,
                voice=piper_voice,
                length_scale=float(length_scale),
                speaker_id=int(speaker_id) if speaker_id is not None else None,
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
                                "[piper] emit voice={} seq={} bytes={}",
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

            if self._interrupted and data.voice_id == self._interrupted_voice:
                log.info("[piper] synth interrupted voice={} seq={}", data.voice_id, seq)

            if not (self._interrupted and data.voice_id == self._interrupted_voice) and pcm_chunk and self.required_manager is not None:
                log.info(
                    "[piper] emit tail voice={} seq={} bytes={}",
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

            if data.final and not (self._interrupted and data.voice_id == self._interrupted_voice) and self.required_manager is not None:
                log.info("[piper] emit final voice={} seq={}", data.voice_id, seq)
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
        except PiperVoiceNotAvailableError as exc:
            # Dependency missing or voice model unavailable: log a clear error,
            # close the player lane, and keep the runtime alive.
            log.error("[piper] {} (voice={})", exc, data.voice_id)
            if self.required_manager is not None:
                _ = await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=22_050,
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


# Backwards compatibility alias, matching BosonTTSPlugin convention.
PiperTTSPlugin = PiperTTSAudioOutput