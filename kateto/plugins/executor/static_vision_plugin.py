from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any

from kateto.core.config import PluginSettings
from kateto.core.discovery import discovery_context_for
from kateto.core.event import (
    GenerateData,
    PluginErrorData,
    ScheduleCancelData,
    ScheduleRequestData,
    ScheduleType,
    VisionCaptureTriggerData,
    VisionDescribeRequestData,
    VisionDescribeResultData,
    VisionFrameData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.voices.base import _openai_client
from openai import APIStatusError, BadRequestError


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


# ponytail: 8/64 hamming bound borrowed from video-rag phash_dedupe; dense 1fps
# frames stay conservative and the window always keeps >= 1 frame.
def dedupe_window(
    frames: list[tuple[float, bytes]],
    *,
    hash_bits: int = 64,
    threshold: int = 8,
    fallback_keep: int | None = None,
) -> list[tuple[float, bytes]]:
    try:
        from PIL import Image
    except Exception:
        keep = 5 if fallback_keep is None else max(0, fallback_keep)
        return list(frames[-keep:]) if keep > 0 else []
    side = math.isqrt(hash_bits)
    kept: list[tuple[float, bytes]] = []
    digests: list[int] = []
    for ts, payload in frames:
        try:
            gray = Image.open(io.BytesIO(payload)).convert("L").resize((side + 1, side))
            px = gray.tobytes()
            digest = 0
            for y in range(side):
                row = y * (side + 1)
                for x in range(side):
                    digest = (digest << 1) | (1 if px[row + x] > px[row + x + 1] else 0)
            if all((digest ^ known).bit_count() > threshold for known in digests):
                kept.append((ts, payload))
                digests.append(digest)
        except Exception:
            kept.append((ts, payload))
    return kept


def _vision_api_key() -> str:
    """Primary/fallback vision endpoint key (factory precedent: no-key default for local servers)."""
    return os.environ.get("OPENAI_API_KEY") or "sk-no-key-required"


def _data_url(payload: bytes) -> str:
    """Wrap raw frame bytes as a data-URL (PNG magic sniff, else JPEG)."""
    mime = "image/png" if payload[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def _completion_text(response: Any) -> str:
    """Extract assistant text from a chat completion (empty string, never raise)."""
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


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
        self._opted_in = self.opted_in
        # ponytail: unknown opt-in voices land here with a reason instead of a job.
        self._periodic_skipped: dict[str, str] = {}
        # ponytail: todo-4 lane adds maxlen bounds + drop counting on these same names.
        self._windows: dict[str, deque[tuple[float, bytes]]] = {}
        self._dropped: dict[str, int] = {}
        # ponytail: todo-9 lane appends stable per-voice job ids here; disable cancels them.
        self._periodic_jobs: list[str] = []
        self._capture_task: asyncio.Task[None] | None = None
        # ponytail: todo-5 lane opens the webcam handle; disable releases it.
        self._webcam_handle: Any | None = None
        self._webcam_unavailable: str | None = None
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
                from kateto.voices.skills import ensure_shared_skill

                ensure_shared_skill(self._config_dir, "look-at")
            except Exception:
                pass

    async def enable(self) -> None:
        await super().enable()
        await self._schedule_periodic()
        if self._capture_task is not None and not self._capture_task.done():
            return
        self._capture_task = asyncio.create_task(
            self._capture_loop(), name=f"kateto-vision-capture-{self.name}"
        )

    async def _schedule_periodic(self) -> None:
        """Emit ONE stable INTERVAL schedule_request per opted-in voice (todo 9)."""
        pairs = tuple(self._opted_in)
        if not pairs or self.manager is None:
            return
        known = {p.name for p in self.manager.get_plugins() if "voice" in p.capabilities}
        for voice, interval in pairs:
            job_id = f"vision-describe-{voice}"
            if job_id in self._periodic_jobs:
                continue
            if known and voice not in known:
                self._periodic_skipped[voice] = f"unknown voice {voice!r} (known: {sorted(known)})"
                continue
            await self.required_manager.emit(
                "schedule_request",
                ScheduleRequestData(
                    schedule_type=ScheduleType.INTERVAL,
                    expression=interval,
                    event_name="vision_describe_request",
                    data={"requester": f"scheduler:{voice}"},
                    job_id=job_id,
                    target_voice=voice,
                ),
                source=self.name,
            )
            self._periodic_jobs.append(job_id)

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

    async def on_vision_describe_request(self, data: Any = None) -> None:
        manager = self.required_manager
        if isinstance(data, dict):
            data = VisionDescribeRequestData.model_validate(data)
        requester: str = data.requester
        source: str = data.source or "auto"
        max_images = data.max_images if data.max_images and data.max_images > 0 else 5
        correlation_id = data.correlation_id

        async def emit_result(
            text: str,
            *,
            frame_count: int = 0,
            kept_count: int = 0,
            dropped: int = 0,
            window_start: float = 0.0,
            window_end: float = 0.0,
            via: str = "primary",
        ) -> None:
            await manager.emit(
                "vision_describe_result",
                VisionDescribeResultData(
                    text=text,
                    frame_count=frame_count,
                    kept_count=kept_count,
                    dropped=dropped,
                    window_start=window_start,
                    window_end=window_end,
                    source=source,
                    via=via,
                    correlation_id=correlation_id,
                ),
                source=self.name,
            )

        if source not in ("auto", "screen", "webcam"):
            await emit_result(f'unknown source "{source}" (valid: auto, screen, webcam)')
            return

        wanted = (
            [s for s in ("screen", "webcam") if self._windows.get(s)]
            if source == "auto"
            else [source]
        )
        snapshots = {s: list(self._windows.get(s, ())) for s in wanted}
        if not any(snapshots.values()):
            if source == "webcam" and self._webcam_unavailable:
                await emit_result(f"webcam unavailable: {self._webcam_unavailable}")
            else:
                await emit_result("no frames captured yet")
            return

        sections: list[tuple[str, list[tuple[float, bytes]], int, str, list[Any]]] = []
        for name in wanted:
            frames = snapshots[name]
            if not frames:
                continue
            kept = dedupe_window(frames, fallback_keep=max_images)[:max_images]
            if not kept:
                continue
            t0 = kept[0][0]
            labels = ", ".join(f"t+{ts - t0:.1f}s" for ts, _ in kept)
            prompt = (
                f"Describe what happens across these {len(kept)} {name} frames "
                f"(oldest to newest: {labels}). One short timestamped description."
            )
            content: list[Any] = [{"type": "text", "text": prompt}]
            content += [
                {"type": "image_url", "image_url": {"url": _data_url(payload), "detail": "low"}}
                for _, payload in kept
            ]
            sections.append((name, kept, len(frames), prompt, content))
        if not sections:
            await emit_result("no frames captured yet")
            return

        headers = {"x-kateto-requester": requester}
        if self.vision_endpoint and self.vision_model:
            try:
                texts = {
                    name: _completion_text(
                        await _openai_client(
                            self.vision_endpoint, _vision_api_key(), 1, self.vision_timeout
                        ).chat.completions.create(
                            model=self.vision_model,
                            messages=[{"role": "user", "content": content}],
                            max_tokens=self.vision_max_tokens,
                            timeout=self.vision_timeout,
                            extra_headers=headers,
                        )
                    )
                    for name, _kept, _total, _prompt, content in sections
                }
                via = "primary"
            except (BadRequestError, APIStatusError) as error:
                if getattr(error, "status_code", 400) != 400:
                    raise
                texts, via = await self._fallback_texts(headers, sections)
        else:
            texts, via = await self._fallback_texts(headers, sections)

        def section_span(kept: list[tuple[float, bytes]]) -> float:
            return kept[-1][0] - kept[0][0] if len(kept) > 1 else 0.0

        fused = "\n".join(
            f"--- {name} ({section_span(kept):.0f}s, {len(kept)}/{total} frames) ---\n{texts[name]}"
            for name, kept, total, _, _ in sections
        )
        all_ts = [ts for _, kept, _, _, _ in sections for ts, _ in kept]
        frame_count = sum(total for _, _, total, _, _ in sections)
        kept_count = sum(len(kept) for _, kept, _, _, _ in sections)
        dropped = sum(self._dropped.get(name, 0) for name, _, _, _, _ in sections)
        window_start, window_end = min(all_ts), max(all_ts)
        await emit_result(
            fused,
            frame_count=frame_count,
            kept_count=kept_count,
            dropped=dropped,
            window_start=window_start,
            window_end=window_end,
            via=via,
        )
        if requester.startswith("scheduler:"):
            voice = requester.split("scheduler:", 1)[1]
            if voice and kept_count > 0:
                span = window_end - window_start
                await manager.emit(
                    "generate",
                    GenerateData(prompt=f"[look-at {source} {span:.0f}s]: {fused}"),
                    source=self.name,
                    target=voice,
                )

    async def _fallback_texts(
        self,
        headers: dict[str, str],
        sections: list[tuple[str, list[tuple[float, bytes]], int, str, list[Any]]],
    ) -> tuple[dict[str, str], str]:
        prompt = "\n".join(text for _, _, _, text, _ in sections)
        content: list[Any] = [{"type": "text", "text": prompt}]
        for _, _, _, _, parts in sections:
            content += [part for part in parts if part.get("type") != "text"]
        text, via = await self._describe_fallback(prompt, content, headers, sections)
        return {name: text for name, _, _, _, _ in sections}, via

    async def _describe_fallback(
        self,
        prompt: str,
        content: list[Any],
        headers: dict[str, str],
        sections: list[tuple[str, list[tuple[float, bytes]], int, str, list[Any]]],
    ) -> tuple[str, str]:
        images = [
            part["image_url"]["url"] for part in content if part.get("type") == "image_url"
        ]
        try:
            context = discovery_context_for((self,))
            mcp = getattr(context, "external_mcp", None) if context is not None else None
            if mcp is not None:
                result = await mcp.try_call_tool(
                    ["video_rag"], "describe_images", {"prompt": prompt, "images": images}
                )
                if result is not None:
                    return str(result), "sidecar"
        except Exception:
            pass
        fallback_model = self.vision_fallback_model or self.vision_model
        if self.vision_fallback_endpoint and fallback_model:
            try:
                response = await _openai_client(
                    self.vision_fallback_endpoint, _vision_api_key(), 1, self.vision_timeout
                ).chat.completions.create(
                    model=fallback_model,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=self.vision_max_tokens,
                    timeout=self.vision_timeout,
                    extra_headers=headers,
                )
                return _completion_text(response), "fallback-vlm"
            except (BadRequestError, APIStatusError) as error:
                if getattr(error, "status_code", 400) != 400:
                    raise
        details = "; ".join(
            f"{name}: {len(kept)}/{total} frames over "
            f"{(kept[-1][0] - kept[0][0]) if len(kept) > 1 else 0.0:.1f}s"
            for name, kept, total, _, _ in sections
        )
        return (
            "recap (vision not configured: set vision_endpoint/vision_model "
            f"or enable the video-rag sidecar): {details}",
            "recap",
        )

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

    def _capture_webcam(self) -> bytes | None:
        try:
            import cv2
        except Exception as error:
            self._webcam_unavailable = f"opencv unavailable: {error}"
            return None
        try:
            handle = self._webcam_handle
            if handle is None:
                handle = cv2.VideoCapture(self.device_index)
                setter = getattr(handle, "set", None)
                if callable(setter):
                    try:
                        setter(3, 640)
                        setter(4, 480)
                    except Exception:
                        pass
                self._webcam_handle = handle
            is_opened = getattr(handle, "isOpened", None)
            if callable(is_opened) and not is_opened():
                self._webcam_unavailable = "webcam open failed"
                return None
            ok, frame = handle.read()
            if not ok or frame is None:
                self._webcam_unavailable = "webcam read failed"
                return None
            encoder = getattr(cv2, "imencode", None)
            if encoder is None:
                self._webcam_unavailable = "webcam encode unavailable"
                return None
            quality_flag = int(getattr(cv2, "IMWRITE_JPEG_QUALITY", 1))
            enc_ok, buf = encoder(".jpg", frame, [quality_flag, 60])
            if not enc_ok or buf is None:
                self._webcam_unavailable = "webcam encode failed"
                return None
            raw = buf.tobytes() if hasattr(buf, "tobytes") else bytes(buf)
            data = bytes(raw)
            self._webcam_unavailable = None
            self._append_frame("webcam", data, time.time())
            return data
        except Exception as error:
            self._webcam_unavailable = f"webcam error: {error}"
            return None


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
