from __future__ import annotations

import base64
import time
from typing import Any

from loguru import logger
from starlette.websockets import WebSocketDisconnect

from kateto.core.event import AudioOutput, InterruptData
from kateto.core.rms import calculate_raw_rms

MASK_PROTOCOL = 1

_SPEAKING_RMS_THRESHOLD = 0.05


class MaskAudioBridge:
    """Server→phone bridge for MASK-5: serves PCM audio over the /ws/mask socket.

    MASK-2 owns the endpoint; this class only exposes ``serve(ws)`` to hang
    from ``@app.websocket("/ws/mask")`` and forwards ``AudioOutput`` /
    ``InterruptData`` events to every connected phone.
    """

    def __init__(self) -> None:
        self._sockets: set[Any] = set()
        self.turn_active: bool = False
        self.frames_sent: int = 0

    @property
    def connected(self) -> int:
        return len(self._sockets)

    async def register(self, ws: Any) -> None:
        self._sockets.add(ws)
        try:
            await ws.send_json({"event": "mask_ready", "type": "ready", "protocol": MASK_PROTOCOL})
        except Exception:
            logger.debug("mask ws ready send failed, dropping socket")
            self._sockets.discard(ws)

    async def unregister(self, ws: Any) -> None:
        self._sockets.discard(ws)

    async def serve(self, ws: Any) -> None:
        await ws.accept()
        await self.register(ws)
        try:
            # No client→server protocol in this card: inbound messages are ignored.
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.debug(f"mask ws receive failed: {exc}")
        finally:
            await self.unregister(ws)

    def frame_for(self, data: AudioOutput) -> dict[str, Any] | None:
        """Pure: build the JSON-able audio frame, or None when there is nothing to send."""
        if not data.samples and not data.final:
            return None

        samples = data.samples
        if data.rms is not None:
            rms = data.rms
        else:
            rms = calculate_raw_rms(samples)
        rms = max(0.0, min(1.0, rms))

        self.turn_active = not data.final

        words = None
        if data.words is not None:
            words = [
                {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                for w in data.words
            ]

        return {
            "event": "audio_output",
            "type": "audio",
            "protocol": MASK_PROTOCOL,
            "voice_id": data.voice_id,
            "sample_rate": data.sample_rate,
            "channels": data.channels,
            "format": data.format,
            "seq": data.sequence,
            "final": data.final,
            "audio_b64": base64.b64encode(samples).decode("ascii"),
            "n_bytes": len(samples),
            "rms": rms,
            "is_speaking": rms > _SPEAKING_RMS_THRESHOLD and not data.final,
            "text": data.text,
            "words": words,
            "t_ms": int(time.monotonic() * 1000),
        }

    async def on_audio_output(self, data: AudioOutput) -> None:
        try:
            frame = self.frame_for(data)
            if frame is None:
                return
            await self._send_all(frame)
        except Exception as exc:
            logger.warning(f"mask audio_bridge on_audio_output failed: {exc}")

    async def on_interrupt(self, data: InterruptData) -> None:
        self.turn_active = False
        try:
            await self._send_all(
                {
                    "event": "interrupt",
                    "type": "interrupt",
                    "protocol": MASK_PROTOCOL,
                    "reason": data.reason,
                    "dept": data.dept,
                }
            )
        except Exception as exc:
            logger.warning(f"mask audio_bridge on_interrupt failed: {exc}")

    async def _send_all(self, frame: dict[str, Any]) -> None:
        delivered = False
        for ws in list(self._sockets):
            try:
                await ws.send_json(frame)
                delivered = True
            except Exception:
                logger.debug("mask ws send failed, dropping socket")
                self._sockets.discard(ws)
        if delivered:
            self.frames_sent += 1
