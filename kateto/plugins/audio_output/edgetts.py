from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import time
from collections.abc import Mapping
from typing import override

from pydantic import BaseModel

from kateto.core.config import PluginConfigRegistry, PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, EventEnvelope, InterruptData, TextChunk
from kateto.core.plugin import EventHandler, Plugin
from kateto.providers import EdgeTTSProvider

# Register dynamic config parameters contributed by this plugin
PluginConfigRegistry.register_plugin_param("audio_output_edgetts", "default_voice", "en-US-JennyNeural")
PluginConfigRegistry.register_voice_param("edge_tts_voice", None)


class EdgeTTSAudioOutput(Plugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: EdgeTTSProvider | None = None,
        voice_map: Mapping[str, Mapping[str, str]] | None = None,
        default_voice: str | None = None,
    ) -> None:
        super().__init__("audio_output_edgetts")
        self._provider: EdgeTTSProvider = EdgeTTSProvider(settings) if provider is None else provider
        self._voice_map = dict(voice_map) if voice_map is not None else {}
        self._default_voice: str = (
            default_voice
            or getattr(settings, "default_voice", None)
            or (settings.get("default_voice") if hasattr(settings, "get") else None)
            or settings.default_language
            or "en-US-JennyNeural"
        )
        self._stream: bool = settings.stream
        self._provider_active: bool = False
        self._interrupted: bool = False
        self._interrupted_voice: str | None = None
        self._interrupted_at: float = 0.0
        self._current_voice: str | None = None
        self._stream_task: asyncio.Task[None] | None = None
        self._playing = False
        self._status_emitted = False
        self._buffer: dict[str, list[str]] = {}
        self._buffer_task: asyncio.Task[None] | None = None

    @override
    async def initialize(self) -> None:
        manager = self.required_manager
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("audio_output", AudioOutput)
        manager.register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def enable(self) -> None:
        if not self._provider_active:
            _ = await self._provider.__aenter__()
            self._provider_active = True

    @override
    async def _enqueue(
        self, envelope: EventEnvelope[BaseModel], handler: EventHandler
    ) -> None:
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case _:
                await super()._enqueue(envelope, handler)

    @override
    async def disable(self) -> None:
        if self._provider_active:
            await self._cancel_stream()
            await self._provider.aclose()
            self._provider_active = False

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
            if data.final and self.required_manager is not None:
                await self.required_manager.emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=24_000,
                        channels=1,
                        format="pcm_s16le",
                        voice_id=data.voice_id,
                        final=True,
                    ),
                    source=self.name,
                )
            return

        if self._stream:
            task = asyncio.create_task(self._emit_pcm(data), name=f"kateto-edgetts-{data.voice_id}")
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
        else:
            self._buffer.setdefault(data.voice_id, []).append(data.text)
            if data.final:
                full_text = "".join(self._buffer.pop(data.voice_id, []))
                if full_text.strip():
                    synthetic = TextChunk(text=full_text, sequence=data.sequence, final=True, voice_id=data.voice_id)
                    task = asyncio.create_task(self._emit_pcm(synthetic), name=f"kateto-edgetts-{data.voice_id}")
                    self._buffer_task = task
                    try:
                        await task
                    except asyncio.CancelledError:
                        if not self._interrupted:
                            raise
                    finally:
                        if self._buffer_task is task:
                            self._buffer_task = None
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
        if self._buffer_task is not None and not self._buffer_task.done():
            return True
        return False

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self._interrupted = True
        self._interrupted_voice = self._current_voice
        self._interrupted_at = time.monotonic()
        if self._current_voice:
            self._buffer.pop(self._current_voice, None)
        else:
            self._buffer.clear()
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
        edge_voice: str = voice_config.get("edge_tts_voice") or self._default_voice
        await self._set_playing(True)
        try:
            out_sample_rate = 24_000
            out_channels = 1
            out_format = "pcm_s16le"
            seq = 0
            pcm_chunk = bytearray()
            CHUNK_THRESHOLD = 16384

            async for output in self._provider.stream_sentence(data, voice=edge_voice):
                if self._interrupted and data.voice_id == self._interrupted_voice:
                    break
                out_sample_rate = output.sample_rate
                out_channels = output.channels
                out_format = output.format
                if output.samples:
                    pcm_chunk.extend(output.samples)
                    if len(pcm_chunk) >= CHUNK_THRESHOLD:
                        if self.required_manager is not None:
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
                                ),
                                source=self.name,
                            )
                            seq += 1
                        pcm_chunk.clear()

            if not (self._interrupted and data.voice_id == self._interrupted_voice) and pcm_chunk and self.required_manager is not None:
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
                    ),
                    source=self.name,
                )
                seq += 1
                pcm_chunk.clear()

            if not (self._interrupted and data.voice_id == self._interrupted_voice) and self.required_manager is not None:
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
                    ),
                    source=self.name,
                )
        finally:
            await self._set_playing(False)
            if not self.is_busy:
                self._idle_event.set()

    async def _cancel_stream(self) -> None:
        for task in (self._stream_task, self._buffer_task):
            if task is None or task.done():
                continue
            _ = task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._stream_task = None
        self._buffer_task = None

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

