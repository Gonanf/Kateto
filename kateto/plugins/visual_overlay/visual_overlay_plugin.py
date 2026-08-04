from __future__ import annotations

import asyncio
import math
import struct
from typing import Any

from kateto.core.event import AudioOutput, TextChunk
from kateto.core.plugin import Plugin


class VisualOverlayPlugin(Plugin):
    """Plugin managing visual overlay subtitles and audio RMS visemes."""

    def __init__(self, name: str = "visual_overlay") -> None:
        super().__init__(name=name, capabilities=("system", "visual_overlay"))
        self._connected_websockets: set[Any] = set()

    async def initialize(self) -> None:
        pass

    def compute_rms(self, pcm_data: bytes) -> float:
        if not pcm_data:
            return 0.0
        # Assume 16-bit PCM samples
        count = len(pcm_data) // 2
        if count == 0:
            return 0.0
        try:
            samples = struct.unpack(f"<{count}h", pcm_data[: count * 2])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / count) / 32768.0
            return min(1.0, rms)
        except Exception:
            return 0.0

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
            await self._broadcast({"type": "subtitle", "text": data.text, "voice_id": data.voice_id})

    async def on_audio_output(self, data: AudioOutput) -> None:
        rms = self.compute_rms(data.samples)
        await self._broadcast({"type": "viseme", "rms": rms, "voice_id": data.voice_id})
