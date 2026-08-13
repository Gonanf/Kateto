from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from kateto.core.event import BaseModel, EventEnvelope
from kateto.core.manager import PluginManager


@dataclass(frozen=True, slots=True)
class TraceFilters:
    events: frozenset[str] = frozenset()
    voices: frozenset[str] = frozenset()


def _timestamp_text(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M:%S.") + f"{timestamp.microsecond // 1_000:03d}"


def format_trace_line(
    *,
    timestamp: datetime,
    delta_ms: int,
    event: str,
    source: str,
    targets: tuple[str, ...],
) -> str:
    targets_text = ",".join(targets) if targets else "-"
    return f"{_timestamp_text(timestamp)} +{delta_ms:>6}ms {event} {source} -> {targets_text}"


def _stderr_line(line: str) -> None:
    print(line, file=sys.stderr)


class EventTracer:
    def __init__(
        self,
        *,
        filters: TraceFilters | None = None,
        writer: Callable[[str], None] | None = None,
    ) -> None:
        self._filters: TraceFilters = filters or TraceFilters()
        self._writer: Callable[[str], None] = writer or _stderr_line
        self._last_timestamp: datetime | None = None

    def attach(self, manager: PluginManager) -> None:
        manager.add_dispatch_observer(self._on_dispatch)

    def _on_dispatch(
        self,
        envelope: EventEnvelope[BaseModel],
        targets: tuple[str, ...],
    ) -> None:
        if not self._matches(envelope, targets):
            return
        last = self._last_timestamp
        delta_ms = round((envelope.timestamp - last).total_seconds() * 1_000) if last else 0
        self._last_timestamp = envelope.timestamp
        self._writer(
            format_trace_line(
                timestamp=envelope.timestamp,
                delta_ms=delta_ms,
                event=envelope.name,
                source=envelope.source,
                targets=targets,
            )
        )

    def _matches(
        self,
        envelope: EventEnvelope[BaseModel],
        targets: tuple[str, ...],
    ) -> bool:
        if self._filters.events and envelope.name.casefold() not in self._filters.events:
            return False
        if not self._filters.voices:
            return True
        candidates = {envelope.source.casefold(), *(t.casefold() for t in targets)}
        voice_field = getattr(envelope.data, "voice", None)
        if isinstance(voice_field, str):
            candidates.add(voice_field.casefold())
        return bool(candidates & self._filters.voices)
