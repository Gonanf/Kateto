from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import AsyncIterator
from typing import override

from collections.abc import Mapping

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, InterruptData, TextChunk
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.providers import EdgeTTSProvider


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
        self._default_voice: str = default_voice or settings.default_language or "en-US-JennyNeural"
        self._stream: bool = settings.stream
        self._provider_active: bool = False
        self._interrupted: bool = False
        self._stream_task: asyncio.Task[None] | None = None
        self._playing = False
        self._status_emitted = False
        self._buffer: dict[str, list[str]] = {}
        self._buffer_task: asyncio.Task[None] | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("audio_output", AudioOutput)
        manager.register_event("audio_output_status", AudioOutputStatusData)

    @override
    async def enable(self) -> None:
        if not self._provider_active:
            _ = await self._provider.__aenter__()
            self._provider_active = True
        await self._set_playing(False)

    @override
    async def disable(self) -> None:
        await self._cancel_stream()
        if self._provider_active:
            await self._provider.aclose()
            self._provider_active = False

    async def on_text_chunk(self, data: TextChunk) -> None:
        if data.voice_id is None:
            return
        self._interrupted = False
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

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self._interrupted = True
        self._buffer.clear()
        await self._cancel_stream()

    async def _emit_pcm(self, data: TextChunk) -> None:
        voice_id_str = data.voice_id
        if voice_id_str is None:
            return
        voice_config = self._voice_map.get(voice_id_str, {})
        edge_voice: str = voice_config.get("edge_tts_voice") or self._default_voice
        await self._set_playing(True)
        pcm_buffer = bytearray()
        out_sample_rate = 24_000
        out_channels = 1
        out_format = "pcm_s16le"
        out_voice_id = edge_voice
        async for output in self._provider.stream_sentence(data, voice=edge_voice):
            out_sample_rate = output.sample_rate
            out_channels = output.channels
            out_format = output.format
            out_voice_id = output.voice_id or edge_voice
            if output.samples:
                pcm_buffer.extend(output.samples)
            if output.final and pcm_buffer:
                _ = await self._manager().emit(
                    "audio_output",
                    AudioOutput(
                        samples=bytes(pcm_buffer),
                        sample_rate=out_sample_rate,
                        channels=out_channels,
                        format=out_format,
                        voice_id=out_voice_id,
                        sequence=0,
                        final=False,
                    ),
                    source=self.name,
                )
                _ = await self._manager().emit(
                    "audio_output",
                    AudioOutput(
                        samples=b"",
                        sample_rate=out_sample_rate,
                        channels=out_channels,
                        format=out_format,
                        voice_id=out_voice_id,
                        sequence=1,
                        final=True,
                    ),
                    source=self.name,
                )
                pcm_buffer.clear()

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
            msg = "audio_output_edgetts must be enabled before use"
            raise RuntimeError(msg)
        return manager
