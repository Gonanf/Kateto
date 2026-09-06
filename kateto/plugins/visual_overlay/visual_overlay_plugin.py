from __future__ import annotations

import asyncio
from typing import Any

import base64

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, InterruptData, OverlayLayout, TextChunk
from kateto.core.plugin import Plugin
from kateto.core.rms import (
    RMSProcessor,
    calculate_raw_rms,
    map_rms_to_jaw_transform,
    map_rms_to_puppet_transform,
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
        self._last_debate_state: dict[str, Any] | None = None
        self._debate_history: list[dict[str, Any]] = []

        self._layout: str = "multi"
        self._voices: list[str] = ["jane", "doktor", "conquest", "whisperer"]
        self._stream_audio: bool = True
        if settings is not None:
            self._layout = getattr(settings, "layout", None) or settings.get("layout", "multi")
            cfg_voices = getattr(settings, "voices", None) or settings.get("voices", None)
            if cfg_voices:
                self._voices = list(cfg_voices)
            raw_audio = getattr(settings, "audio", None) if getattr(settings, "audio", None) is not None else settings.get("audio", None)
            if raw_audio is not None:
                self._stream_audio = bool(raw_audio)

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
        if self._last_debate_state is not None:
            try:
                await ws.send_json(self._last_debate_state)
            except Exception:
                pass

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

    async def on_overlay_layout(self, data: Any) -> None:
        """Handle programmatic layout and position updates (e.g. for games, chess, versus)."""
        layout = getattr(data, "layout", None) or (data.get("layout") if isinstance(data, dict) else "row")
        positions = getattr(data, "positions", None) or (data.get("positions") if isinstance(data, dict) else {})
        voices = getattr(data, "voices", None) or (data.get("voices") if isinstance(data, dict) else None)
        payload = {
            "event": "overlay_layout",
            "type": "layout",
            "layout": layout,
            "positions": positions,
            "voices": voices,
        }
        await self._broadcast(payload)

    async def on_interrupt(self, data: InterruptData) -> None:
        """Broadcast interrupt event so browser immediately silences audio and stops mouth."""
        # P1-1: reset EMA so jaw closes immediately between turns
        for proc in self._rms_processors.values():
            proc.reset()
        self._default_processor.reset()
        payload = {
            "event": "interrupt",
            "type": "interrupt",
            "reason": getattr(data, "reason", "interrupt"),
            "voice_id": getattr(data, "voice_id", None),
        }
        await self._broadcast(payload)

    async def on_debate(self, data: Any) -> None:
        """Persist debate state for /api/courtroom/state even without WS overlay connected (P1-7)."""
        try:
            packed = data.model_dump() if hasattr(data, "model_dump") else (dict(data) if isinstance(data, dict) else {})
        except Exception:
            packed = {}
        if packed and isinstance(packed, dict):
            state: dict[str, Any] = packed if packed.get("event") == "debate" else {"event": "debate", **packed}
            self._last_debate_state = state
            self._debate_history.append(state)
            if len(self._debate_history) > 50:
                self._debate_history.pop(0)
            await self._broadcast(state)

    async def update_viseme(self, voice_id: str | None, rms: float, text: str | None = None) -> None:
        """Direct data-layer update for viseme/RMS kinematics, bypassing event bus dispatch."""
        is_speaking = bool(rms > 0.05)
        puppet = map_rms_to_puppet_transform(rms)
        payload = {
            "event": "audio_output",
            "type": "viseme",
            "voice_id": voice_id,
            "rms": rms,
            "is_speaking": is_speaking,
            "jawOffsetX": puppet["jawOffsetX"],
            "jawOffsetY": puppet["jawOffsetY"],
            "jawRotation": puppet["jawRotation"],
            "headOffsetY": puppet["headOffsetY"],
            "text": text,
            "data": {
                "rms": rms,
                "is_speaking": is_speaking,
                "voice_id": voice_id,
                "jawOffsetX": puppet["jawOffsetX"],
                "jawOffsetY": puppet["jawOffsetY"],
                "jawRotation": puppet["jawRotation"],
                "headOffsetY": puppet["headOffsetY"],
                "text": text,
            },
        }
        await self._broadcast(payload)

    async def on_audio_output(self, data: AudioOutput) -> None:
        if data.rms is not None:
            rms = data.rms
        else:
            rms = self.compute_rms(data.samples, voice_id=data.voice_id)

        # P1-1: on final chunk reset EMA so next turn starts closed
        if data.final:
            proc = self._rms_processors.get(data.voice_id or "")
            if proc is not None:
                proc.reset()
            self._default_processor.reset()

        is_speaking = bool(rms > 0.05 and not data.final)
        puppet = map_rms_to_puppet_transform(rms)

        audio_b64 = None
        if data.samples and self._stream_audio:
            audio_b64 = base64.b64encode(data.samples).decode("ascii")

        payload = {
            "event": "audio_output",
            "type": "viseme",
            "voice_id": data.voice_id,
            "rms": rms,
            "is_speaking": is_speaking,
            "jawOffsetX": puppet["jawOffsetX"],
            "jawOffsetY": puppet["jawOffsetY"],
            "jawRotation": puppet["jawRotation"],
            "headOffsetY": puppet["headOffsetY"],
            "text": data.text,
            "audio": audio_b64,
            "sample_rate": data.sample_rate,
            "channels": data.channels,
            "format": data.format,
            "final": data.final,
            "data": {
                "rms": rms,
                "is_speaking": is_speaking,
                "voice_id": data.voice_id,
                "jawOffsetX": puppet["jawOffsetX"],
                "jawOffsetY": puppet["jawOffsetY"],
                "jawRotation": puppet["jawRotation"],
                "headOffsetY": puppet["headOffsetY"],
                "text": data.text,
                "audio": audio_b64,
                "sample_rate": data.sample_rate,
                "channels": data.channels,
                "format": data.format,
                "final": data.final,
            },
        }
        await self._broadcast(payload)


from kateto.core.config import register_plugin_param

register_plugin_param("visual_overlay", "layout", "multi")
register_plugin_param("visual_overlay", "voices", ["jane", "doktor", "conquest", "whisperer"])
register_plugin_param("visual_overlay", "audio", True)
