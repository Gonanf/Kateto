from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from collections.abc import AsyncIterator
from typing import override

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, InterruptData, TextChunk
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.providers import CambProvider


class CambAudioOutput(Plugin):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        provider: CambProvider | None = None,
        voice_map: dict[str, dict] | None = None,
        default_voice_id: int | None = None,
        default_language: str | None = None,
    ) -> None:
        super().__init__("audio_output_camb")
        self._provider: CambProvider = CambProvider(settings) if provider is None else provider
        self._voice_map: dict[str, dict] = voice_map if voice_map is not None else {}
        self._default_voice_id: int = default_voice_id or settings.default_voice_id or 147320
        self._default_language: str = default_language or settings.default_language or "en-us"
        self._provider_active: bool = False
        self._interrupted: bool = False
        self._stream_task: asyncio.Task[None] | None = None
        self._playing = False
        self._status_emitted = False

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
        task = asyncio.create_task(self._emit_pcm(data), name=f"kateto-camb-{data.voice_id}")
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

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self._interrupted = True
        await self._cancel_stream()

    async def _emit_pcm(self, data: TextChunk) -> None:
        voice_id_str = data.voice_id
        if voice_id_str is None:
            return
        voice_config = self._voice_map.get(voice_id_str, {})
        camb_voice_id: int = voice_config.get("camb_voice_id") or self._default_voice_id
        camb_language: str = voice_config.get("camb_language") or self._default_language
        await self._set_playing(True)
        async for output in self._provider.stream_sentence(
            data,
            voice_id=camb_voice_id,
            language=camb_language,
        ):
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
            msg = "audio_output_camb must be enabled before use"
            raise RuntimeError(msg)
        return manager
