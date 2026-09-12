from __future__ import annotations

import asyncio
import io
import math
import os
import subprocess
import time
from collections import deque
from pathlib import Path
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


# ponytail: JPEG floor-accept — q60→q40→q30, then accept whatever remains; never raise.
_FRAME_BYTE_CAP = 128 * 1024


def _encode_bounded(img: Any) -> bytes:
    """Encode a PIL image to bounded JPEG bytes (max side 640, 128KB cap, floor-accept)."""
    from PIL import Image

    width, height = img.size
    longest = max(width, height)
    if longest > 640:
        scale = 640.0 / longest
        img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    encoded = b""
    for quality in (60, 40, 30):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        encoded = buf.getvalue()
        if len(encoded) <= _FRAME_BYTE_CAP:
            return encoded
    return encoded


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
        window_secs: float = 5.0,
        # Config dir for the look-at skill backfill; None disables it (tests).
        config_dir: Path | None = None,
    ) -> None:
        super().__init__(name=name, capabilities=("vision", "static_vision"))
        self._settings = settings
        # Backward-compat kwargs stay the default; a settings key overrides when present.
        self.interval_seconds = _setting(settings, "interval_seconds", interval_seconds)
        self.target_pid = _setting(settings, "target_pid", target_pid)
        self.dept = _setting(settings, "dept", dept)
        self.source_default = _setting(settings, "source_default", "screen")
        self.window_secs = _setting(settings, "window_secs", window_secs)
        if self.window_secs <= 0:
            raise ValueError(f"window_secs must be positive, got {self.window_secs!r}")
        self.capture_fps = _setting(settings, "capture_fps", capture_fps)
        self._maxlen = max(1, math.ceil(self.window_secs * self.capture_fps))
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
        self._config_dir = config_dir

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("vision_frame", VisionFrameData)
            self.manager.register_event("vision_capture_trigger", VisionCaptureTriggerData)
            self.manager.register_event("vision_describe_request", VisionDescribeRequestData)
            self.manager.register_event("vision_describe_result", VisionDescribeResultData)
        if self._config_dir is not None:
            # ponytail: narrow backfill exception — bootstrap skips existing config
            # dirs, so the skill file is copied here; failures degrade silently and
            # surface later as SkillLoadError at voice load.
            try:
                from kateto.voices.skills import SkillLoadError, ensure_shared_skill

                ensure_shared_skill(self._config_dir, "look-at")
            except (OSError, SkillLoadError):
                pass

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
        dq = self._windows.get(source)
        if dq is None:
            dq = self._windows[source] = deque(maxlen=self._maxlen)
        if len(dq) == dq.maxlen:
            self._dropped[source] = self._dropped.get(source, 0) + 1
        dq.append((ts, frame))

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
                try:
                    return _encode_bounded(img)
                except Exception:
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


from kateto.core.config import register_plugin_param, register_voice_param

register_plugin_param("executor_vision", "source_default", "screen")
register_plugin_param("executor_vision", "window_secs", 5.0)
register_plugin_param("executor_vision", "capture_fps", 1.0)
register_plugin_param("executor_vision", "describe_interval", "30s")
register_plugin_param("executor_vision", "vision_endpoint", None)
register_plugin_param("executor_vision", "vision_model", None)
register_plugin_param("executor_vision", "vision_max_tokens", 300)
register_plugin_param("executor_vision", "vision_timeout", 60.0)
register_plugin_param("executor_vision", "vision_fallback_endpoint", None)
register_plugin_param("executor_vision", "vision_fallback_model", None)
register_plugin_param("executor_vision", "device_index", 0)
register_voice_param("vision_periodic", False)
register_voice_param("vision_interval", "30s")
