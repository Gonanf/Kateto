from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from kateto.core.plugin import Plugin

logger = logging.getLogger(__name__)

# ponytail: hard cap per logged field; real logs may want per-field limits
MAX_TEXT_LEN = 4000


def _truncate(text: str, limit: int = MAX_TEXT_LEN) -> str:
    """Collapse newlines and hard-truncate to `limit` chars."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[:limit]
    return flat


def _iso_with_offset(ts: float) -> str:
    """ISO 8601 with local UTC offset."""
    return datetime.fromtimestamp(ts).astimezone().isoformat()


class ConversationLogPlugin(Plugin):
    """Append-only JSONL log of the whole conversation per session day.

    Writes one JSON object per line to
    ``<config_dir>/logs/session-YYYY-MM-DD.jsonl``. Never blocks the bus:
    any write failure is logged as a warning and swallowed.
    """

    def __init__(
        self,
        name: str = "conversation_log",
        *,
        config_dir: Path | None = None,
    ) -> None:
        super().__init__(name=name, capabilities=("logging", "conversation_log"))
        self.config_dir = config_dir
        self.logs_dir: Path | None = None

    async def initialize(self) -> None:
        if self.config_dir is None and self.manager is not None:
            self.config_dir = Path.home() / ".config" / "kateto"
        self.logs_dir = (self.config_dir or Path(".")) / "logs"
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("[conversation_log] cannot create logs dir %s: %s", self.logs_dir, e)
            self.logs_dir = None

    def _log_path(self) -> Path | None:
        if self.logs_dir is None:
            return None
        day = datetime.now().strftime("%Y-%m-%d")
        return self.logs_dir / f"session-{day}.jsonl"

    def _append(self, *, event: str, envelope: Any, voice: str, text: str, extra: dict[str, Any]) -> None:
        # The bus calls handlers with data only; envelope is None. Fall back to
        # the envelope the plugin is currently processing (see Plugin._run).
        if envelope is None:
            envelope = self._current_envelope
        now = time.time()
        record = {
            "ts": _iso_with_offset(now),
            "epoch": now,
            "event": event,
            "source": getattr(envelope, "source", "") or "",
            "voice": voice,
            "text": _truncate(text),
            "extra": extra,
        }
        path = self._log_path()
        if path is None:
            return
        try:
            line = json.dumps(record, ensure_ascii=False)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as e:  # noqa: BROAD_EXCEPT_OK - logging must never break the bus
            logger.warning("[conversation_log] failed to append %s: %s", path, e)

    async def on_transcription(self, data: Any, envelope: Any = None) -> None:
        text = getattr(data, "text", "")
        if not text:
            return
        self._append(
            event="user_turn",
            envelope=envelope,
            voice=getattr(envelope, "source", "") or "user",
            text=text,
            extra={
                "language": getattr(data, "language", None),
                "confidence": getattr(data, "confidence", None),
                "duration_ms": getattr(data, "duration_ms", None),
            },
        )

    async def on_text_chunk(self, data: Any, envelope: Any = None) -> None:
        if not getattr(data, "final", False):
            return
        self._append(
            event="voice_turn",
            envelope=envelope,
            voice=getattr(data, "voice_id", None) or "assistant",
            text=getattr(data, "text", ""),
            extra={"sequence": getattr(data, "sequence", 0)},
        )

    async def on_classification(self, data: Any, envelope: Any = None) -> None:
        self._append(
            event="classifier",
            envelope=envelope,
            voice=getattr(data, "voice", None) or "system",
            text=getattr(data, "text", ""),
            extra={
                "category": str(getattr(data, "category", "")),
                "confidence": getattr(data, "confidence", None),
                "workflow": getattr(data, "workflow", None),
                "project_state": str(getattr(data, "project_state", "")),
            },
        )

    async def on_tool_call(self, data: Any, envelope: Any = None) -> None:
        self._append(
            event="tool_call",
            envelope=envelope,
            voice=getattr(data, "voice", "") or "assistant",
            text=str(getattr(data, "tool_name", "")),
            extra={
                "tool": getattr(data, "tool_name", ""),
                "arguments": getattr(data, "arguments", {}) or {},
            },
        )

    async def on_tool_result(self, data: Any, envelope: Any = None) -> None:
        error = getattr(data, "error", None)
        self._append(
            event="tool_result",
            envelope=envelope,
            voice=getattr(data, "voice", "") or "tool",
            text=getattr(data, "result", "") or "",
            extra={
                "tool": getattr(data, "tool_name", ""),
                "ok": error is None,
                "error": error,
            },
        )

    async def on_error(self, data: Any, envelope: Any = None) -> None:
        self._append(
            event="error",
            envelope=envelope,
            voice="system",
            text=str(getattr(data, "message", "")),
            extra={
                "plugin": getattr(data, "plugin", ""),
                "event_name": getattr(data, "event_name", ""),
                "error_type": getattr(data, "error_type", ""),
            },
        )

