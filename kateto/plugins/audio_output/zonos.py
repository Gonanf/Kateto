from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import AsyncIterator
from typing import Protocol, Self, override

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, InterruptData, TextChunk
from kateto.core.plugin import Plugin, PluginManagerProtocol
from kateto.providers import ZonosProvider


class PcmStreamingProvider(Protocol):
    async def __aenter__(self) -> Self: ...

    async def aclose(self) -> None: ...

    def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]: ...


class ZonosAudioOutput(Plugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: PcmStreamingProvider | None = None,
    ) -> None:
        super().__init__("audio_output_zonos")
        self._provider: PcmStreamingProvider = ZonosProvider(settings) if provider is None else provider
        self._provider_active: bool = False
        self._interrupted: bool = False
        self._stream_task: asyncio.Task[None] | None = None

    @override
    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("audio_output", AudioOutput)

    @override
    async def enable(self) -> None:
        if not self._provider_active:
            _ = await self._provider.__aenter__()
            self._provider_active = True

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
        task = asyncio.create_task(self._emit_pcm(data), name=f"kateto-zonos-{data.voice_id}")
        self._stream_task = task
        try:
            await task
        except asyncio.CancelledError:
            if not self._interrupted:
                raise
        finally:
            if self._stream_task is task:
                self._stream_task = None

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self._interrupted = True
        await self._cancel_stream()

    async def _emit_pcm(self, data: TextChunk) -> None:
        voice_id = data.voice_id
        if voice_id is None:
            return
        async for output in self._provider.stream_sentence(data, voice_id=voice_id):
            _ = await self._manager().emit("audio_output", output, source=self.name)

    async def _cancel_stream(self) -> None:
        task = self._stream_task
        if task is None or task.done():
            return
        _ = task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return

    def _manager(self) -> PluginManagerProtocol:
        manager = self.manager
        if manager is None:
            msg = "audio_output_zonos must be enabled before use"
            raise RuntimeError(msg)
        return manager
