from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from kateto.core.plugin import Plugin

logger = logging.getLogger(__name__)

# ponytail: hard cap per logged field; real logs may want per-field limits
MAX_TEXT_LEN = 4000
CLIENT_DEPTS = {"workmatch", "sherut"}


def _truncate(text: str, limit: int = MAX_TEXT_LEN) -> tuple[str, bool]:
    """Collapse newlines and hard-truncate to `limit` chars."""
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[:limit], True
    return flat, False


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
        self.session_id: str = uuid.uuid4().hex
        self._current_turn_id: str | None = None
        self._turn_start_epoch: float = 0.0
        self._turn_input: str = ""
        self._turn_outputs: list[dict[str, Any]] = []
        self._turn_voices: set[str] = set()
        self._turn_idle_voices: set[str] = set()
        self._warned_depts: set[str] = set()
        self._client_blocked_count: int = 0

    async def initialize(self) -> None:
        self.session_id = uuid.uuid4().hex
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

    def _get_dept(self, envelope: Any, data: Any) -> str | None:
        for obj in (envelope, data):
            if obj is None:
                continue
            dept = getattr(obj, "dept", None)
            if dept is None and isinstance(obj, dict):
                dept = obj.get("dept")
            if dept is not None and isinstance(dept, str):
                return dept
        if hasattr(self, "_current_envelope") and self._current_envelope is not None:
            dept = getattr(self._current_envelope, "dept", None)
            if dept is None and isinstance(self._current_envelope, dict):
                dept = self._current_envelope.get("dept")
            if dept is not None and isinstance(dept, str):
                return dept
        return None

    def _is_client_blocked(self, envelope: Any, data: Any) -> bool:
        dept = self._get_dept(envelope, data)
        if dept and isinstance(dept, str) and dept.casefold() in CLIENT_DEPTS:
            dept_key = dept.casefold()
            if dept_key not in self._warned_depts:
                self._warned_depts.add(dept_key)
                logger.warning("[conversation_log] blocking client event for dept: %s", dept)
            self._client_blocked_count += 1
            return True
        return False

    def _close_turn(self, closed_by: str) -> None:
        if self._current_turn_id is None:
            return
        now = time.time()

        distinct_voices = {out["voice"] for out in self._turn_outputs if out.get("voice")}
        ambiguity: list[str] = []
        if len(distinct_voices) > 1:
            ambiguity.append("multi_voice")
        if len(self._turn_outputs) == 0:
            ambiguity.append("no_output")
        if not self._turn_input:
            ambiguity.append("no_input")

        ambiguous = len(ambiguity) > 0

        record = {
            "schema": "turn/v1",
            "event": "turn_end",
            "session_id": self.session_id,
            "turn_id": self._current_turn_id,
            "ts_start": _iso_with_offset(self._turn_start_epoch),
            "ts_end": _iso_with_offset(now),
            "closed_by": closed_by,
            "input": self._turn_input,
            "outputs": self._turn_outputs,
            "ambiguous": ambiguous,
            "ambiguity": ambiguity,
            "client_blocked": False,
        }

        path = self._log_path()
        if path is not None:
            try:
                line = json.dumps(record, ensure_ascii=False)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception as e:  # noqa: BROAD_EXCEPT_OK
                logger.warning("[conversation_log] failed to write turn_end %s: %s", path, e)

        # Reset turn state
        self._current_turn_id = None
        self._turn_start_epoch = 0.0
        self._turn_input = ""
        self._turn_outputs = []
        self._turn_voices = set()
        self._turn_idle_voices = set()

    def _append(
        self,
        *,
        event: str,
        envelope: Any,
        voice: str,
        text: str,
        extra: dict[str, Any],
        turn_id: Any = ...,
    ) -> None:
        # The bus calls handlers with data only; envelope is None. Fall back to
        # the envelope the plugin is currently processing (see Plugin._run).
        if envelope is None:
            envelope = self._current_envelope
        if self._is_client_blocked(envelope, None):
            return
        now = time.time()
        truncated_text, truncated = _truncate(text)
        if truncated:
            extra["truncated"] = True
        actual_turn_id = self._current_turn_id if turn_id is ... else turn_id
        record = {
            "ts": _iso_with_offset(now),
            "epoch": now,
            "session_id": self.session_id,
            "turn_id": actual_turn_id,
            "event": event,
            "source": getattr(envelope, "source", "") or "",
            "voice": voice,
            "text": truncated_text,
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
        if self._is_client_blocked(envelope, data):
            return
        text = getattr(data, "text", "")
        if not text:
            return

        partial = bool(getattr(data, "partial", False))
        if partial:
            extra = {
                "partial": True,
                "language": getattr(data, "language", None),
                "confidence": getattr(data, "confidence", None),
                "duration_ms": getattr(data, "duration_ms", None),
            }
            self._append(
                event="user_turn_partial",
                envelope=envelope,
                voice=getattr(envelope, "source", "") or "user",
                text=text,
                extra=extra,
            )
            return

        if self._current_turn_id is not None:
            self._close_turn(closed_by="next_transcription")

        turn_id = uuid.uuid4().hex
        self._current_turn_id = turn_id
        self._turn_start_epoch = time.time()
        self._turn_input = text
        self._turn_outputs = []
        self._turn_voices = set()
        self._turn_idle_voices = set()

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
            turn_id=turn_id,
        )

    async def on_text_chunk(self, data: Any, envelope: Any = None) -> None:
        if self._is_client_blocked(envelope, data):
            return
        if not getattr(data, "final", False):
            return
        text = getattr(data, "text", "")
        voice = getattr(data, "voice_id", None) or "assistant"
        seq = getattr(data, "sequence", 0)

        extra: dict[str, Any] = {"sequence": seq}
        if self._current_turn_id is None:
            extra["unsolicited"] = True
            turn_id = None
        else:
            turn_id = self._current_turn_id
            self._turn_voices.add(voice)
            voice_entry = None
            for out in self._turn_outputs:
                if out["voice"] == voice:
                    voice_entry = out
                    break
            if voice_entry is None:
                self._turn_outputs.append({
                    "voice": voice,
                    "text": text,
                    "sequence_first": seq,
                    "sequence_last": seq,
                })
            else:
                voice_entry["text"] = f"{voice_entry['text']} {text}".strip() if voice_entry["text"] else text
                voice_entry["sequence_first"] = min(voice_entry["sequence_first"], seq)
                voice_entry["sequence_last"] = max(voice_entry["sequence_last"], seq)

        self._append(
            event="voice_turn",
            envelope=envelope,
            voice=voice,
            text=text,
            extra=extra,
            turn_id=turn_id,
        )

    async def on_voice_idle(self, data: Any, envelope: Any = None) -> None:
        if self._is_client_blocked(envelope, data):
            return
        if self._current_turn_id is None:
            return
        voice = (
            getattr(data, "voice", None)
            or getattr(data, "voice_id", None)
            or getattr(envelope, "source", None)
        )
        if voice:
            self._turn_idle_voices.add(voice)
        if self._turn_voices and self._turn_voices.issubset(self._turn_idle_voices):
            self._close_turn(closed_by="voice_idle")

    async def on_interrupt(self, data: Any = None, envelope: Any = None) -> None:
        if self._is_client_blocked(envelope, data):
            return
        if self._current_turn_id is not None:
            self._close_turn(closed_by="interrupt")

    async def on_classification(self, data: Any, envelope: Any = None) -> None:
        if self._is_client_blocked(envelope, data):
            return
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
        if self._is_client_blocked(envelope, data):
            return
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
        if self._is_client_blocked(envelope, data):
            return
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
        if self._is_client_blocked(envelope, data):
            return
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
