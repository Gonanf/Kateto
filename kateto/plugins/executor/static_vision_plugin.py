from __future__ import annotations

import asyncio
import io
import os
import subprocess
import time
from collections import deque
from typing import Any

from kateto.core.config import PluginSettings
from kateto.core.event import (
    PluginErrorData,
    ScheduleCancelData,
    VisionCaptureTriggerData,
    VisionDescribeRequestData,
    VisionDescribeResultData,
    VisionFrameData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


def _setting(settings: PluginSettings | None, key: str, default: Any) -> Any:
    """Dual getattr-or-get access (visual_overlay precedent); kwarg default wins when absent."""
    if settings is None:
        return default
    value = getattr(settings, key, None)
    if value is None:
        value = settings.get(key, None)
    return default if value is None else value


class StaticVisionPlugin(Plugin):
    """Plugin for capturing static vision frames (screen / process window)."""

    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        name: str = "static_vision",
        interval_seconds: float = 10.0,
        target_pid: int | None = None,
        dept: str = "fun",
        opted_in: tuple[tuple[str, str], ...] = (),
        # Compat: parallel lanes pass capture_fps as a kwarg; settings key wins when present.
        capture_fps: float = 1.0,
    ) -> None:
        super().__init__(name=name, capabilities=("vision", "static_vision"))
        self._settings = settings
        # Backward-compat kwargs stay the default; a settings key overrides when present.
        self.interval_seconds = _setting(settings, "interval_seconds", interval_seconds)
        self.target_pid = _setting(settings, "target_pid", target_pid)
        self.dept = _setting(settings, "dept", dept)
        # Vision settings keys with plan defaults.
        self.source_default = _setting(settings, "source_default", "screen")
        self.window_secs = _setting(settings, "window_secs", 5.0)
        self.capture_fps = _setting(settings, "capture_fps", capture_fps)
        self.describe_interval = _setting(settings, "describe_interval", "30s")
        self.vision_endpoint = _setting(settings, "vision_endpoint", None)
        self.vision_model = _setting(settings, "vision_model", None)
        self.vision_max_tokens = _setting(settings, "vision_max_tokens", 300)
        self.vision_timeout = _setting(settings, "vision_timeout", 60.0)
        self.vision_fallback_endpoint = _setting(settings, "vision_fallback_endpoint", None)
        self.vision_fallback_model = _setting(settings, "vision_fallback_model", None)
        self.device_index = _setting(settings, "device_index", 0)
        # Factory-built from the voice table (todo 9 consumes); never read here.
        self.opted_in = tuple(opted_in)
        # ponytail: todo-4 lane adds maxlen bounds + drop counting on these same names.
        self._windows: dict[str, deque[tuple[float, bytes]]] = {}
        self._dropped: dict[str, int] = {}
        # ponytail: todo-9 lane appends stable per-voice job ids here; disable cancels them.
        self._periodic_jobs: list[str] = []
        self._capture_task: asyncio.Task[None] | None = None
        # ponytail: todo-5 lane opens the webcam handle; disable releases it.
        self._webcam_handle: Any | None = None

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("vision_frame", VisionFrameData)
            self.manager.register_event("vision_capture_trigger", VisionCaptureTriggerData)
            self.manager.register_event("vision_describe_request", VisionDescribeRequestData)
            self.manager.register_event("vision_describe_result", VisionDescribeResultData)

    async def enable(self) -> None:
        await super().enable()
        if self._capture_task is not None and not self._capture_task.done():
            return
        self._capture_task = asyncio.create_task(
            self._capture_loop(), name=f"kateto-vision-capture-{self.name}"
        )

    async def disable(self) -> None:
        task, self._capture_task = self._capture_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        handle, self._webcam_handle = self._webcam_handle, None
        if handle is not None:
            release = getattr(handle, "release", None)
            if callable(release):
                try:
                    release()
                except Exception:
                    pass
        for job_id in list(self._periodic_jobs):
            await self.required_manager.emit(
                "schedule_cancel", ScheduleCancelData(job_id=job_id), source=self.name
            )
        self._periodic_jobs.clear()
        await super().disable()

    def _append_frame(self, source: str, frame: bytes, ts: float) -> None:
        # No lock: the producer appends in the event loop after to_thread returns.
        self._windows.setdefault(source, deque()).append((ts, frame))

    async def _capture_loop(self) -> None:
        source = "screen"
        interval = 1.0 / self.capture_fps if self.capture_fps > 0 else 1.0
        while True:
            try:
                # ponytail: target_pid threading stays as-is; per-source capture is todo 5.
                frame_bytes = await asyncio.to_thread(self.capture_frame, self.target_pid)
                if frame_bytes:
                    self._append_frame(source, frame_bytes, time.time())
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self.required_manager.emit(
                    "error",
                    PluginErrorData(
                        plugin=self.name,
                        event_name="vision_capture",
                        error_type=type(error).__name__,
                        message=str(error),
                    ),
                    source=self.name,
                )
            await asyncio.sleep(interval)

    async def on_vision_capture_trigger(self, data: Any = None) -> None:
        """Trigger handler for static vision capture."""
        frame_bytes = self.capture_frame(self.target_pid)
        if frame_bytes:
            ts = time.time()
            self._append_frame("screen", frame_bytes, ts)
            event_data = VisionFrameData(
                frame=frame_bytes,
                source_pid=self.target_pid,
                ts=ts,
                dept=self.dept,
            )
            await self.required_manager.emit("vision_frame", event_data, source=self.name)

    def capture_frame(self, target_pid: int | None = None) -> bytes:
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

        # 1. Wayland check via grim if Wayland session
        if session_type == "wayland" and target_pid is None:
            try:
                res = subprocess.run(["grim", "-"], capture_output=True, check=True)
                if res.stdout:
                    return res.stdout
            except Exception:
                pass

        # 2. mss full screen capture
        try:
            import mss
            from PIL import Image

            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
        except Exception:
            pass

        # 3. Fallback dummy PNG bytes (1x1 red pixel PNG)
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )
