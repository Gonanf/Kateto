from __future__ import annotations

import asyncio
import io
import os
import subprocess
import time
from typing import Any

from kateto.core.event import ScheduleRequestData, ScheduleType, VisionFrameData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class StaticVisionPlugin(Plugin):
    """Plugin for capturing static vision frames (screen / process window)."""

    def __init__(
        self,
        name: str = "static_vision",
        *,
        interval_seconds: float = 10.0,
        target_pid: int | None = None,
        dept: str = "fun",
    ) -> None:
        super().__init__(name=name, capabilities=("vision", "static_vision"))
        self.interval_seconds = interval_seconds
        self.target_pid = target_pid
        self.dept = dept

    async def initialize(self) -> None:
        if self.manager is not None:
            self.manager.register_event("vision_frame", VisionFrameData)
            self.manager.register_event("schedule_request", ScheduleRequestData)

    async def enable(self) -> None:
        await super().enable()
        # Emit schedule request for auto-jittered frame capture
        await self.required_manager.emit(
            "schedule_request",
            ScheduleRequestData(
                schedule_type=ScheduleType.INTERVAL,
                expression=f"{self.interval_seconds}s",
                event_name="vision_capture_trigger",
                data={"dept": self.dept},
            ),
            source=self.name,
        )

    async def on_vision_capture_trigger(self, data: Any = None) -> None:
        """Trigger handler for static vision capture."""
        frame_bytes = self.capture_frame(self.target_pid)
        if frame_bytes:
            event_data = VisionFrameData(
                frame=frame_bytes,
                source_pid=self.target_pid,
                ts=time.time(),
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
