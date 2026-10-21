"""MASK-4: phone (POV) camera frames -> Kateto vision bus.

The MASK-2 WS endpoint feeds raw/base64 JPEG frames here; this plugin validates
them, gates the rate, keeps a bounded in-memory ring buffer and emits
``vision_frame`` events on the bus. No network, no disk, no threads.
"""

from __future__ import annotations

import base64
import binascii
import time
from typing import Any

from kateto.core.config import PluginSettings
from kateto.core.event import VisionFrameData
from kateto.core.plugin import Plugin
from loguru import logger


def _setting(settings: PluginSettings | None, key: str, default: Any) -> Any:
    """Dual getattr-or-get access (static_vision precedent)."""
    if settings is None:
        return default
    value = getattr(settings, key, None)
    if value is None:
        value = settings.get(key, None)
    return default if value is None else value


# JPEG SOI magic: every accepted frame must start with it.
_JPEG_MAGIC = b"\xff\xd8"


class MaskCameraPlugin(Plugin):
    """Accepts camera frames and emits ``vision_frame`` events (no I/O)."""

    def __init__(
        self,
        name: str = "mask_camera",
        settings: PluginSettings | None = None,
    ) -> None:
        super().__init__(name=name, capabilities=("vision", "mask_camera"))
        self._settings = settings
        self.camera_buffer_frames = max(1, int(_setting(settings, "camera_buffer_frames", 30)))
        self.camera_max_fps = max(0.1, float(_setting(settings, "camera_max_fps", 10.0)))
        self.camera_frame_byte_cap = max(1, int(_setting(settings, "camera_frame_byte_cap", 524288)))
        self.camera_dept = str(_setting(settings, "camera_dept", "fun"))
        self.camera_source = str(_setting(settings, "camera_source", "mask_camera"))
        # ponytail: plain list, not deque — the cap is honoured on append so a
        # direct attribute override (tests) is authoritative too.
        self._buffer: list[VisionFrameData] = []
        self._last_ts: float | None = None
        self._stats: dict[str, int] = {
            "frames_in": 0,
            "frames_emitted": 0,
            "dropped_invalid": 0,
            "dropped_rate": 0,
            "dropped_disabled": 0,
            "emit_errors": 0,
        }
        self.register_config_param("camera_buffer_frames", 30)
        self.register_config_param("camera_max_fps", 10.0)
        self.register_config_param("camera_frame_byte_cap", 524288)
        self.register_config_param("camera_dept", "fun")
        self.register_config_param("camera_source", "mask_camera")

    async def initialize(self) -> None:
        # Re-registering the same contract is idempotent.
        if self.manager is not None:
            self.manager.register_event("vision_frame", VisionFrameData)

    @staticmethod
    def _decode_jpeg(frame: bytes | bytearray | str) -> bytes | None:
        """bytes/bytearray pass through; str is base64 (data-URL prefix allowed)."""
        if isinstance(frame, (bytes, bytearray)):
            return bytes(frame)
        if not isinstance(frame, str):
            return None
        text = frame.strip()
        if text.startswith("data:"):
            _, sep, tail = text.partition(",")
            if not sep:
                return None
            text = tail
        text = "".join(text.split())
        if not text:
            return None
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return None

    async def submit_frame(
        self,
        frame: bytes | bytearray | str,
        *,
        ts: float | None = None,
        source: str | None = None,
        dept: str | None = None,
    ) -> bool:
        """Validate and accept one camera frame; never raises."""
        try:
            if self.manager is None or not self.enabled:
                self._stats["dropped_disabled"] += 1
                return False

            jpeg = self._decode_jpeg(frame)
            if (
                jpeg is None
                or not jpeg
                or len(jpeg) > self.camera_frame_byte_cap
                or jpeg[:2] != _JPEG_MAGIC
            ):
                self._stats["dropped_invalid"] += 1
                logger.debug("[mask_camera] dropped invalid frame (type={})", type(frame).__name__)
                return False

            now = time.monotonic() if ts is None else float(ts)
            min_interval = 1.0 / self.camera_max_fps
            if self._last_ts is not None and now - self._last_ts < min_interval:
                self._stats["dropped_rate"] += 1
                return False
            self._last_ts = now

            data = VisionFrameData(
                frame=jpeg,
                ts=now,
                dept=self.camera_dept if dept is None else str(dept),
                source=self.camera_source if source is None else str(source),
            )
            self._buffer.append(data)
            while len(self._buffer) > self.camera_buffer_frames:
                self._buffer.pop(0)
            self._stats["frames_in"] += 1
            self._stats["frames_emitted"] += 1
            try:
                await self.manager.emit("vision_frame", data, source=self.name)
            except Exception as error:  # noqa: BROAD_EXCEPT_OK
                self._stats["emit_errors"] += 1
                logger.debug("[mask_camera] emit failed: {}", error)
            return True
        except Exception as error:  # noqa: BROAD_EXCEPT_OK
            logger.debug("[mask_camera] submit_frame failed: {}", error)
            return False

    async def submit_payload(self, payload: dict[str, Any]) -> bool:
        """Accept the raw client JSON: frame/image/data + optional ts/source."""
        try:
            if not isinstance(payload, dict):
                return False
            frame = payload.get("frame")
            if frame is None:
                frame = payload.get("image")
            if frame is None:
                frame = payload.get("data")
            if frame is None or not isinstance(frame, (str, bytes, bytearray)):
                return False
            raw_ts = payload.get("ts")
            ts = float(raw_ts) if isinstance(raw_ts, (int, float)) and not isinstance(raw_ts, bool) else None
            raw_source = payload.get("source")
            source = str(raw_source) if isinstance(raw_source, str) else None
            return await self.submit_frame(frame, ts=ts, source=source)
        except Exception as error:  # noqa: BROAD_EXCEPT_OK
            logger.debug("[mask_camera] submit_payload failed: {}", error)
            return False

    def latest_frame(self) -> VisionFrameData | None:
        return self._buffer[-1] if self._buffer else None

    def frame_window(self, window_secs: float) -> list[VisionFrameData]:
        """Frames whose ts falls within window_secs of the newest accepted frame."""
        if window_secs <= 0 or not self._buffer:
            return []
        reference = self._last_ts if self._last_ts is not None else self._buffer[-1].ts
        cutoff = reference - float(window_secs)
        return [frame for frame in self._buffer if frame.ts >= cutoff]

    def stats(self) -> dict[str, int | float | None]:
        return {
            "frames_in": self._stats["frames_in"],
            "frames_emitted": self._stats["frames_emitted"],
            "dropped_invalid": self._stats["dropped_invalid"],
            "dropped_rate": self._stats["dropped_rate"],
            "dropped_disabled": self._stats["dropped_disabled"],
            "emit_errors": self._stats["emit_errors"],
            "buffer_frames": len(self._buffer),
            "last_ts": self._last_ts,
        }

    async def shutdown(self) -> None:
        self._buffer.clear()
        self._last_ts = None

    async def disable(self) -> None:
        await self.shutdown()
        await super().disable()
