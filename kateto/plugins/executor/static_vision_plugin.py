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
    ScheduleResultData,
    ScheduleType,
    VisionCaptureTriggerData,
    VisionDescribeRequestData,
    VisionDescribeResultData,
    VisionFrameData,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.voices.base import _openai_client
from loguru import logger
from openai import APIStatusError, BadRequestError

log = logger


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

# Sidecar describe budget floor: a native 1920x1080 frame costs the VLM
# ~2350 vision tokens at ~66 tok/s prefill (~36 s) plus generation, so the
# 30 s MCP default always loses. The vision timeout applies, never below this.
_SIDECAR_TIMEOUT_FLOOR = 120.0

# video-rag rejects oversized frames (`image {i} exceeds ~1.5MB data-URL cap`):
# never send a data-URL longer than this; drop the frame with a log instead.
_SIDECAR_URL_CAP = 1_500_000

# 1x1 red pixel PNG: capture fallback headless + VLM prewarm payload.
_PREWARM_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


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


def _cap_frames(
    kept: list[tuple[float, bytes]], limit: int
) -> list[tuple[float, bytes]]:
    """Trim a deduped window to *limit* frames, oldest + newest first.

    Each frame costs the VLM ~2350 vision tokens (~36 s prefill at ~66 tok/s),
    so periodic narration sends 2 by default: the oldest and the newest, which
    is what shows the change. Wider limits keep evenly-spaced frames; a limit
    of 1 keeps the newest.
    """
    if limit <= 0 or len(kept) <= limit:
        return list(kept)
    if limit == 1:
        return [kept[-1]]
    return [kept[round(i * (len(kept) - 1) / (limit - 1))] for i in range(limit)]


def _compress_for_sidecar(payload: bytes, *, max_width: int) -> bytes | None:
    """Fit a frame under the sidecar data-URL cap at `max_width`, aspect kept.

    Passthrough when already small (never upscale or re-encode for fun).
    Otherwise downscale to `max_width` JPEG with a quality ladder, shrinking
    further while over the cap. `None` = never fits: the caller drops it.
    Small URL but over-wide images still go through the ladder: byte size is
    not the only cost, pixel count is what the VLM prefills (~2350 tokens for
    a native 1920x1080 frame).
    """
    try:
        from PIL import Image
    except Exception:
        return payload if len(_data_url(payload)) <= _SIDECAR_URL_CAP else None

    small_url = len(_data_url(payload)) <= _SIDECAR_URL_CAP
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            narrow = probe.size[0] <= max_width
            if small_url and narrow:
                return payload
            orig = probe.convert("RGB")
            ow, oh = orig.size
    except Exception:
        return payload if small_url else None
    widths = [max_width]
    width = max_width
    while width > 640:
        width = int(width * 0.75)
        widths.append(width)
    for target in widths:
        frame = orig
        if ow > target:
            frame = orig.resize(
                (target, max(1, round(oh * target / ow))), Image.Resampling.LANCZOS
            )
        for quality in (70, 55, 40):
            buf = io.BytesIO()
            frame.save(buf, format="JPEG", quality=quality)
            out = buf.getvalue()
            if len(_data_url(out)) <= _SIDECAR_URL_CAP:
                return out
    return None


def _dhash(payload: bytes, hash_bits: int = 64) -> int | None:
    """Perceptual dHash (64 bits) of a frame payload; None when undecodable."""
    try:
        from PIL import Image
    except Exception:
        return None
    side = math.isqrt(hash_bits)
    try:
        gray = Image.open(io.BytesIO(payload)).convert("L").resize((side + 1, side))
    except Exception:
        return None
    px = gray.tobytes()
    digest = 0
    for y in range(side):
        row = y * (side + 1)
        for x in range(side):
            digest = (digest << 1) | (1 if px[row + x] > px[row + x + 1] else 0)
    return digest


def _hamming(a: int, b: int) -> int:
    """Hamming distance between two dHash digests."""
    return (a ^ b).bit_count()


def _caption_ratio(a: str, b: str) -> float:
    """Case-insensitive similarity ratio between two captions (0..1)."""
    import difflib

    return difflib.SequenceMatcher(None, a.strip().casefold(), b.strip().casefold()).ratio()


def _describe_prompt(count: int, name: str, labels: str) -> str:
    """Opinion-ready VLM prompt in Spanish: brief facts + what stands out."""
    return (
        f"Describí en español lo que se ve en estas {count} imágenes de {name} "
        f"(de la más vieja a la más nueva: {labels}). "
        "Una descripción breve con marcas temporales. "
        "Agregá qué es lo que más llama la atención y qué cambió "
        "entre la primera y la última imagen. "
        "No inventes nada que no se vea en las imágenes."
    )


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


def _window_span(
    frames: list[tuple[float, bytes]],
    kept: list[tuple[float, bytes]],
    window_secs: float,
) -> float:
    """Real window duration: full capture range when it moves, else the asked window.

    Dedupe collapses a still scene to a single kept frame whose own span is 0 —
    reporting that claims a 0s look. One kept frame means "still", so the asked
    window stands; with several kept frames the capture range (≈ real duration)
    stands. Never 0 when window_secs is positive.
    """
    if len(kept) > 1 and len(frames) > 1:
        elapsed = frames[-1][0] - frames[0][0]
        if elapsed > 0:
            return elapsed
    return window_secs


def _is_sidecar_error(text: str) -> bool:
    """True when sidecar text is an error report, not a description.

    The video-rag sidecar answers errors as text (see its src/mcp.rs:
    `video-rag describe_images: VLM unreachable at ... (model ...)`), and our
    own MCP client returns `{"error": ...}` JSON on timeouts — both arrive here
    as plain strings, so match their shapes instead of a flag we never kept.
    """
    stripped = text.strip()
    if stripped.startswith('{"error"'):
        return True
    head = stripped[:400]
    return "video-rag describe_images:" in head or "VLM unreachable" in head


class StaticVisionPlugin(Plugin):
    """Plugin for capturing static vision frames (screen / process window)."""

    # ponytail: short backoff until the schedule_result ack lands; one WARNING
    # at exhaustion, never a loop. Tests shrink this via instance override.
    _RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0, 30.0, 30.0)

    # Grace before the VLM prewarm fires: plugins enable before
    # external_mcp.start_all(), so an immediate sidecar call would always miss.
    _PREWARM_DELAY_SECS: float = 10.0

    @property
    def _sidecar_timeout(self) -> float:
        """Sidecar describe budget: `vision_timeout`, never below the floor."""
        try:
            base = float(self.vision_timeout)
        except (TypeError, ValueError):
            base = 60.0
        return max(base, _SIDECAR_TIMEOUT_FLOOR)

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
        max_frames_per_describe: int = 2,
        vision_sidecar_max_width: int = 1024,
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
        self.max_frames_per_describe = _setting(
            settings, "max_frames_per_describe", max_frames_per_describe
        )
        self.vision_sidecar_max_width = _setting(
            settings, "vision_sidecar_max_width", vision_sidecar_max_width
        )
        self.device_index = _setting(settings, "device_index", 0)
        self.vision_repeat_hamming_max = int(_setting(settings, "vision_repeat_hamming_max", 6))
        self.vision_repeat_text_min_ratio = float(_setting(settings, "vision_repeat_text_min_ratio", 0.9))
        # Last narrated window per source: {"dhash": int|None, "caption": str}.
        self._last_narrated: dict[str, dict[str, Any]] = {}
        # Factory-built from the voice table (todo 9 consumes); never read here.
        self.opted_in = tuple(opted_in)
        self._opted_in = self.opted_in
        # ponytail: unknown opt-in voices land here with a reason instead of a job.
        self._periodic_skipped: dict[str, str] = {}
        # Recap carries no real description: periodic ticks stay silent after
        # one warning, while direct user asks still get their "could not see" reply.
        self._recap_narration_warned = False
        # ponytail: todo-4 lane adds maxlen bounds + drop counting on these same names.
        self._windows: dict[str, deque[tuple[float, bytes]]] = {}
        self._dropped: dict[str, int] = {}
        # ponytail: todo-9 lane appends stable per-voice job ids here; disable cancels them.
        self._periodic_jobs: list[str] = []
        # Pending voice -> interval until the schedule_result ack lands.
        self._periodic_pending: dict[str, str] = {}
        self._periodic_retry_tasks: dict[str, asyncio.Task[None]] = {}
        self._capture_task: asyncio.Task[None] | None = None
        self._prewarm_task: asyncio.Task[None] | None = None
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
            self.manager.register_event("schedule_result", ScheduleResultData)
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
        if not self._opted_in:
            log.warning(
                "[vision] periodic describe idle: no voice sets vision_periodic=true "
                "(describe_interval/window_secs alone do not schedule anything)"
            )
        else:
            log.info(
                "[vision] periodic describe opted in: {}",
                ", ".join(f"{voice}@{interval}" for voice, interval in self._opted_in),
            )
        if not (self.vision_endpoint and self.vision_model) and not (
            self.vision_fallback_endpoint and self.vision_fallback_model
        ):
            log.warning(
                "[vision] no VLM endpoint configured (vision_endpoint/vision_model): "
                "describes fall back to the video-rag sidecar if present, else a text recap"
            )
        await self._schedule_periodic()
        if self._opted_in and (
            self._prewarm_task is None or self._prewarm_task.done()
        ):
            self._prewarm_task = asyncio.create_task(
                self._prewarm_vlm(), name=f"kateto-vision-prewarm-{self.name}"
            )
        if self._capture_task is not None and not self._capture_task.done():
            return
        self._capture_task = asyncio.create_task(
            self._capture_loop(), name=f"kateto-vision-capture-{self.name}"
        )

    async def _schedule_periodic(self) -> None:
        pairs = tuple(self._opted_in)
        if not pairs or self.manager is None:
            return
        for voice, interval in pairs:
            job_id = f"vision-describe-{voice}"
            if job_id in self._periodic_jobs or voice in self._periodic_pending:
                continue
            self._periodic_pending[voice] = interval
            await self._try_emit_schedule(voice, interval)
            self._spawn_retry(voice)

    async def _try_emit_schedule(self, voice: str, interval: str) -> bool:
        manager = self.manager
        if manager is None:
            return False
        known = {p.name for p in manager.get_plugins() if "voice" in p.capabilities}
        if known and voice not in known:
            self._periodic_skipped[voice] = f"unknown voice {voice!r} (known: {sorted(known)})"
            return False
        job_id = f"vision-describe-{voice}"
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
        return True

    def _spawn_retry(self, voice: str) -> None:
        existing = self._periodic_retry_tasks.get(voice)
        if existing is not None and not existing.done():
            return
        self._periodic_retry_tasks[voice] = asyncio.create_task(
            self._retry_loop(voice), name=f"kateto-vision-retry-{voice}"
        )

    async def _retry_loop(self, voice: str) -> None:
        attempts = 1
        try:
            for delay in self._RETRY_DELAYS:
                await asyncio.sleep(delay)
                if voice not in self._periodic_pending:
                    return
                if f"vision-describe-{voice}" in self._periodic_jobs:
                    self._periodic_pending.pop(voice, None)
                    return
                interval = self._periodic_pending.get(voice)
                if interval is None:
                    return
                attempts += 1
                await self._try_emit_schedule(voice, interval)
            if voice in self._periodic_pending and f"vision-describe-{voice}" not in self._periodic_jobs:
                reason = self._periodic_skipped.get(voice, "no schedule_result ack received")
                log.warning(
                    "[vision] vision-describe-{} NOT registered after {} attempts "
                    "(is executor_scheduler enabled?) ({})",
                    voice, attempts, reason,
                )
                self._periodic_pending.pop(voice, None)
        except asyncio.CancelledError:
            raise
        finally:
            self._periodic_retry_tasks.pop(voice, None)

    async def on_schedule_result(self, data: Any = None) -> None:
        if isinstance(data, dict):
            data = ScheduleResultData.model_validate(data)
        job_id: str = data.job_id
        prefix = "vision-describe-"
        if not job_id.startswith(prefix):
            return
        voice = job_id.removeprefix(prefix)
        if voice not in self._periodic_pending:
            return
        if data.error:
            if "already scheduled" in data.error:
                interval = self._periodic_pending.pop(voice, "")
                task = self._periodic_retry_tasks.pop(voice, None)
                if task is not None:
                    task.cancel()
                if job_id not in self._periodic_jobs:
                    self._periodic_jobs.append(job_id)
                log.info("[vision] scheduled {} every {} for {}", job_id, interval, voice)
                return
            reason = data.error
            self._periodic_skipped[voice] = reason
            log.warning("[vision] schedule failed for {}: {}", job_id, reason)
            task = self._periodic_retry_tasks.pop(voice, None)
            if task is not None:
                task.cancel()
            self._periodic_pending.pop(voice, None)
            return
        interval = self._periodic_pending.pop(voice, "")
        task = self._periodic_retry_tasks.pop(voice, None)
        if task is not None:
            task.cancel()
        self._periodic_skipped.pop(voice, None)
        if job_id not in self._periodic_jobs:
            self._periodic_jobs.append(job_id)
        log.info("[vision] scheduled {} every {} for {}", job_id, interval, voice)

    async def disable(self) -> None:
        task, self._capture_task = self._capture_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        prewarm, self._prewarm_task = self._prewarm_task, None
        if prewarm is not None and not prewarm.done():
            prewarm.cancel()
            try:
                await prewarm
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
        pending_tasks = list(self._periodic_retry_tasks.values())
        self._periodic_retry_tasks.clear()
        self._periodic_pending.clear()
        for retry in pending_tasks:
            retry.cancel()
        for retry in pending_tasks:
            try:
                await retry
            except asyncio.CancelledError:
                pass
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
        window_secs = (
            data.window_secs
            if data.window_secs is not None and data.window_secs > 0
            else self.window_secs
        )

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
            log.info(
                "[vision] describe requester={} source={} via={} frames={}/{} chars={}",
                requester, source, via, kept_count, frame_count, len(text),
            )
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

        sections: list[
            tuple[str, list[tuple[float, bytes]], int, str, list[Any], list[tuple[float, bytes]]]
        ] = []
        per_describe = self.max_frames_per_describe
        frame_limit = (
            min(max_images, per_describe)
            if per_describe and per_describe > 0
            else max_images
        )
        for name in wanted:
            frames = snapshots[name]
            if not frames:
                continue
            kept = _cap_frames(
                dedupe_window(frames, fallback_keep=max_images), frame_limit
            )
            if not kept:
                continue
            t0 = kept[0][0]
            labels = ", ".join(f"t+{ts - t0:.1f}s" for ts, _ in kept)
            prompt = _describe_prompt(len(kept), name, labels)
            content: list[Any] = [{"type": "text", "text": prompt}]
            content += [
                {"type": "image_url", "image_url": {"url": _data_url(payload), "detail": "low"}}
                for _, payload in kept
            ]
            sections.append((name, kept, len(frames), prompt, content, frames))
        if not sections:
            await emit_result("no frames captured yet")
            return

        is_periodic = requester.startswith("scheduler:")
        cur_hash: dict[str, int | None] = {
            name: _dhash(kept[-1][1]) for name, kept, _, _, _, _ in sections
        }
        if is_periodic:
            voice = requester.split("scheduler:", 1)[1]
            dists: dict[str, int] = {}
            all_repeat = bool(self._last_narrated)
            for name, _, _, _, _, _ in sections:
                prev = self._last_narrated.get(name)
                cur = cur_hash[name]
                if prev is None or prev.get("dhash") is None or cur is None:
                    all_repeat = False
                    break
                dist = _hamming(cur, prev["dhash"])
                dists[name] = dist
                if dist > self.vision_repeat_hamming_max:
                    all_repeat = False
                    break
            if all_repeat and dists:
                detail = ", ".join(f"{n}=hamming {d}/{self.vision_repeat_hamming_max}" for n, d in dists.items())
                log.info(
                    "[vision] periodic narration skipped for {}: imagen repetida ({})",
                    voice, detail,
                )
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
                    for name, _kept, _total, _prompt, content, _frames in sections
                }
                via = "primary"
            except (BadRequestError, APIStatusError) as error:
                if getattr(error, "status_code", 400) != 400:
                    raise
                texts, via = await self._fallback_texts(headers, sections, window_secs)
        else:
            texts, via = await self._fallback_texts(headers, sections, window_secs)

        span_of = {
            name: _window_span(frames, kept, window_secs)
            for name, kept, _, _, _, frames in sections
        }
        start_of = {name: frames[0][0] for name, _, _, _, _, frames in sections}
        fused = "\n".join(
            f"--- {name} ({span_of[name]:.0f}s, {len(kept)}/{total} frames) ---\n{texts[name]}"
            for name, kept, total, _, _, _ in sections
        )
        frame_count = sum(total for _, _, total, _, _, _ in sections)
        kept_count = sum(len(kept) for _, kept, _, _, _, _ in sections)
        dropped = sum(self._dropped.get(name, 0) for name, _, _, _, _, _ in sections)
        window_start = min(start_of.values())
        window_end = max(start + span_of[name] for name, start in start_of.items())
        await emit_result(
            fused,
            frame_count=frame_count,
            kept_count=kept_count,
            dropped=dropped,
            window_start=window_start,
            window_end=window_end,
            via=via,
        )
        if via != "recap" and not is_periodic:
            for name, _, _, _, _, _ in sections:
                self._last_narrated[name] = {"dhash": cur_hash[name], "caption": texts[name]}
        if requester.startswith("scheduler:"):
            voice = requester.split("scheduler:", 1)[1]
            if voice and kept_count > 0:
                if via == "recap":
                    if not self._recap_narration_warned:
                        self._recap_narration_warned = True
                        log.warning(
                            "[vision] periodic narration suppressed for {}: "
                            "no real description (via=recap); "
                            "configure vision_endpoint/vision_model or the video-rag sidecar",
                            voice,
                        )
                    else:
                        log.debug("[vision] periodic narration suppressed for {} (via=recap)", voice)
                    return
                ratios = {
                    name: _caption_ratio(texts[name], self._last_narrated[name]["caption"])
                    for name, _, _, _, _, _ in sections
                    if name in self._last_narrated and self._last_narrated[name].get("caption")
                }
                if ratios and all(r >= self.vision_repeat_text_min_ratio for r in ratios.values()):
                    detail = ", ".join(
                        f"{n}=similitud {r:.2f}>={self.vision_repeat_text_min_ratio:.2f}" for n, r in ratios.items()
                    )
                    log.info(
                        "[vision] periodic narration skipped for {}: caption repetido ({}) caption={!r}",
                        voice, detail, fused[:300],
                    )
                    return
                for name, _, _, _, _, _ in sections:
                    self._last_narrated[name] = {"dhash": cur_hash[name], "caption": texts[name]}
                span = window_end - window_start
                log.info(
                    "[vision] periodic narration -> {} ({}s window) caption={!r}",
                    voice, f"{span:.0f}", fused[:300],
                )
                frames_note = ", 1 frame" if kept_count == 1 else ""
                await manager.emit(
                    "generate",
                    GenerateData(prompt=f"[look-at {source} {span:.0f}s{frames_note}]: {fused}"),
                    source=self.name,
                    target=voice,
                )

    def _lookup_sidecar_mcp(self) -> Any | None:
        try:
            context = discovery_context_for((self,))
        except Exception:
            return None
        mcp = getattr(context, "external_mcp", None) if context is not None else None
        if mcp is None and context is not None:
            # The manager lives in shared services, not on the context field.
            get_shared = getattr(context, "get_shared", None)
            if callable(get_shared):
                try:
                    mcp = get_shared("external_mcp")
                except Exception:
                    mcp = None
        return mcp

    def _sidecar_images(
        self,
        sections: list[
            tuple[str, list[tuple[float, bytes]], int, str, list[Any], list[tuple[float, bytes]]]
        ],
    ) -> tuple[list[str], int]:
        """Compressed data-URLs for the sidecar plus the over-cap drop count."""
        width = self.vision_sidecar_max_width or 1024
        width = max(320, width)
        urls: list[str] = []
        dropped = 0
        for sec in sections:
            name, kept = sec[0], sec[1]
            for _ts, payload in kept:
                squeezed = _compress_for_sidecar(payload, max_width=width)
                if squeezed is None:
                    dropped += 1
                    log.warning(
                        "[vision] sidecar frame dropped ({}): over the ~1.5MB "
                        "data-URL cap even after recompression",
                        name,
                    )
                else:
                    urls.append(_data_url(squeezed))
        return urls, dropped

    async def _prewarm_vlm(self) -> None:
        """One minimal describe so the first real tick skips the model load.

        Best-effort: any failure logs and never surfaces (no error event,
        no narration, no exception out of this task).
        """
        try:
            await asyncio.sleep(self._PREWARM_DELAY_SECS)
            tiny_url = _data_url(_PREWARM_PNG)
            if self.vision_endpoint and self.vision_model:
                await _openai_client(
                    self.vision_endpoint, _vision_api_key(), 1, self.vision_timeout
                ).chat.completions.create(
                    model=self.vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "warmup"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": tiny_url, "detail": "low"},
                                },
                            ],
                        }
                    ],
                    max_tokens=1,
                    timeout=self.vision_timeout,
                    extra_headers={"x-kateto-requester": "prewarm"},
                )
                log.info("[vision] VLM prewarm answered (primary)")
                return
            mcp = self._lookup_sidecar_mcp()
            if mcp is None:
                log.debug("[vision] VLM prewarm skipped: no VLM link configured")
                return
            try_call_result = getattr(mcp, "try_call_tool_result", None)
            if callable(try_call_result):
                result = await try_call_result(
                    ["video_rag"],
                    "describe_images",
                    {"prompt": "warmup", "images": [tiny_url]},
                    timeout=self._sidecar_timeout,
                )
            else:
                result = await mcp.try_call_tool(
                    ["video_rag"], "describe_images", {"prompt": "warmup", "images": [tiny_url]}
                )
            if result is None:
                log.debug("[vision] VLM prewarm skipped: sidecar not up yet")
            else:
                text = result.text if hasattr(result, "text") else str(result)
                log.info("[vision] VLM prewarm answered (sidecar, {} chars)", len(text))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("[vision] VLM prewarm failed (best-effort, ignoring): {}", exc)

    async def _fallback_texts(
        self,
        headers: dict[str, str],
        sections: list[
            tuple[str, list[tuple[float, bytes]], int, str, list[Any], list[tuple[float, bytes]]]
        ],
        window_secs: float | None = None,
    ) -> tuple[dict[str, str], str]:
        prompt = "\n".join(text for _, _, _, text, _, _ in sections)
        content: list[Any] = [{"type": "text", "text": prompt}]
        for _, _, _, _, parts, _ in sections:
            content += [part for part in parts if part.get("type") != "text"]
        text, via = await self._describe_fallback(prompt, content, headers, sections, window_secs)
        return {name: text for name, _, _, _, _, _ in sections}, via

    async def _describe_fallback(
        self,
        prompt: str,
        content: list[Any],
        headers: dict[str, str],
        sections: list[tuple],
        window_secs: float | None = None,
    ) -> tuple[str, str]:
        images, dropped = self._sidecar_images(sections)
        # ponytail: error text is not a description — it falls through to the
        # next link, and only the recap names it (so ambient narration, which
        # suppresses recaps, never voices an error as what it saw).
        sidecar_error: str | None = None
        if not images and dropped:
            sidecar_error = (
                f"all {dropped} frame(s) exceeded the sidecar ~1.5MB data-URL cap "
                "even after recompression (dropped, see warnings)"
            )
            log.warning("[vision] sidecar describe_images skipped: {}", sidecar_error)
        try:
            mcp = self._lookup_sidecar_mcp()
            if mcp is not None and images:
                timeout = self._sidecar_timeout
                log.info(
                    "[vision] sidecar describe_images sending {} frame(s) "
                    "({} dropped over cap) with timeout {}s",
                    len(images),
                    dropped,
                    timeout,
                )
                try_call_result = getattr(mcp, "try_call_tool_result", None)
                if callable(try_call_result):
                    result = await try_call_result(
                        ["video_rag"],
                        "describe_images",
                        {"prompt": prompt, "images": images},
                        timeout=timeout,
                    )
                    if result is not None:
                        text = result.text if hasattr(result, "text") else str(result)
                        log.info(
                            "[vision] sidecar describe_images answered ({} chars): {}",
                            len(text),
                            text[:300],
                        )
                        if len(text) > 300:
                            log.debug("[vision] sidecar describe_images tail: {}", text[300:])
                        flagged = bool(getattr(result, "is_error", False))
                        if flagged or _is_sidecar_error(text):
                            sidecar_error = text
                            log.warning(
                                "[vision] sidecar describe_images error (not a description, {}:{}): {}",
                                getattr(result, "server", "video_rag"),
                                getattr(result, "tool", "describe_images"),
                                text,
                            )
                        else:
                            return text, "sidecar"
                    else:
                        reason_fn = getattr(mcp, "sidecar_reason", None)
                        detail = (
                            reason_fn(["video_rag"], "describe_images")
                            if callable(reason_fn)
                            else "no client or no describe_images tool"
                        )
                        log.warning("[vision] sidecar video_rag unreachable ({})", detail)
                else:
                    result = await mcp.try_call_tool(
                        ["video_rag"], "describe_images", {"prompt": prompt, "images": images}
                    )
                    if result is not None:
                        text = result if isinstance(result, str) else str(result)
                        log.info(
                            "[vision] sidecar describe_images answered ({} chars): {}",
                            len(text),
                            text[:300],
                        )
                        if len(text) > 300:
                            log.debug("[vision] sidecar describe_images tail: {}", text[300:])
                        if _is_sidecar_error(text):
                            sidecar_error = text
                            log.warning(
                                "[vision] sidecar describe_images error (not a description): {}",
                                text,
                            )
                        else:
                            return text, "sidecar"
                    else:
                        reason_fn = getattr(mcp, "sidecar_reason", None)
                        detail = (
                            reason_fn(["video_rag"], "describe_images")
                            if callable(reason_fn)
                            else "no client or no describe_images tool"
                        )
                        log.warning("[vision] sidecar video_rag unreachable ({})", detail)
            elif mcp is None:
                log.warning("[vision] sidecar video_rag unavailable (no external MCP context)")
        except Exception as exc:
            log.warning("[vision] sidecar describe_images failed: {}", exc)
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
        def recap_span(sec: tuple) -> float:
            kept = sec[1]
            if window_secs is not None and len(sec) > 5:
                return _window_span(sec[5], kept, window_secs)
            return kept[-1][0] - kept[0][0] if len(kept) > 1 else 0.0

        details = "; ".join(
            f"{sec[0]}: {len(sec[1])}/{sec[2]} frames over {recap_span(sec):.1f}s"
            for sec in sections
        )
        if sidecar_error is not None:
            return (
                "recap (sidecar describe failed, vision unavailable: "
                f"{sidecar_error}; set vision_endpoint/vision_model "
                f"or fix the video-rag sidecar): {details}",
                "recap",
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
        return _PREWARM_PNG

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
register_plugin_param("executor_vision", "max_frames_per_describe", 2)
register_plugin_param("executor_vision", "vision_sidecar_max_width", 1024)
register_plugin_param("executor_vision", "vision_fallback_endpoint", None)
register_plugin_param("executor_vision", "vision_fallback_model", None)
register_plugin_param("executor_vision", "device_index", 0)
register_plugin_param("executor_vision", "vision_repeat_hamming_max", 6)
register_plugin_param("executor_vision", "vision_repeat_text_min_ratio", 0.9)
register_voice_param("vision_periodic", False)
register_voice_param("vision_interval", "30s")
