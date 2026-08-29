from __future__ import annotations

import asyncio
from typing import Any

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk
from kateto.core.plugin import Plugin
from kateto.core.rms import (
    RMSProcessor,
    calculate_raw_rms,
    map_rms_to_jaw_transform,
    normalize_rms,
)


class VisualOverlayPlugin(Plugin):
    """Plugin managing visual overlay subtitles, muppet cutout jaw transforms, and audio RMS visemes."""

    def __init__(
        self,
        name: str = "visual_overlay",
        settings: PluginSettings | None = None,
    ) -> None:
        super().__init__(name=name, capabilities=("system", "visual_overlay"))
        self._settings = settings
        self._connected_websockets: set[Any] = set()
        self._rms_processors: dict[str, RMSProcessor] = {}
        self._default_processor = RMSProcessor()

    async def initialize(self) -> None:
        pass

    def _get_processor(self, voice_id: str | None = None) -> RMSProcessor:
        key = voice_id or ""
        if key not in self._rms_processors:
            self._rms_processors[key] = RMSProcessor()
        return self._rms_processors[key]

    def compute_rms(self, pcm_data: bytes, voice_id: str | None = None) -> float:
        """Compute EMA-smoothed normalized RMS amplitude (0.0 to 1.0) from PCM bytes."""
        if not pcm_data:
            return 0.0
        processor = self._get_processor(voice_id)
        return processor.process(pcm_data)

    async def register_websocket(self, ws: Any) -> None:
        self._connected_websockets.add(ws)

    async def unregister_websocket(self, ws: Any) -> None:
        self._connected_websockets.discard(ws)

    async def _broadcast(self, data: dict[str, Any]) -> None:
        dead = []
        for ws in list(self._connected_websockets):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connected_websockets.discard(ws)

    async def on_text_chunk(self, data: TextChunk) -> None:
        if data.text:
            payload = {
                "event": "text_chunk",
                "type": "subtitle",
                "text": data.text,
                "voice_id": data.voice_id,
                "data": {
                    "text": data.text,
                    "voice_id": data.voice_id,
                    "sequence": data.sequence,
                    "final": data.final,
                },
            }
            await self._broadcast(payload)

    async def on_audio_output(self, data: AudioOutput) -> None:
        if data.rms is not None:
            rms = data.rms
        else:
            rms = self.compute_rms(data.samples, voice_id=data.voice_id)

        is_speaking = bool(rms > 0.01 and not data.final)
        offset_y, rotation = map_rms_to_jaw_transform(rms)

        payload = {
            "event": "audio_output",
            "type": "viseme",
            "voice_id": data.voice_id,
            "rms": rms,
            "is_speaking": is_speaking,
            "jawOffsetY": offset_y,
            "jawRotation": rotation,
            "text": data.text,
            "data": {
                "rms": rms,
                "is_speaking": is_speaking,
                "voice_id": data.voice_id,
                "jawOffsetY": offset_y,
                "jawRotation": rotation,
                "text": data.text,
            },
        }
        await self._broadcast(payload)
