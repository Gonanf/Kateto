from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class VoiceUpdateTracker:
    """Time-based throttle for per-voice soul/journal updates.

    Keeps a timestamp of the last update per voice and answers the
    question "should we update now?" based on a configurable interval.
    """

    _last_update: dict[str, datetime] = field(default_factory=dict)
    interval_seconds: float = 300.0  # 5 minutes

    def should_update(self, voice: str, now: datetime | None = None) -> bool:
        if now is None:
            now = datetime.now(timezone.utc)
        last = self._last_update.get(voice)
        if last is None:
            return True
        return (now - last).total_seconds() >= self.interval_seconds

    def mark_updated(self, voice: str, now: datetime | None = None) -> None:
        if now is None:
            now = datetime.now(timezone.utc)
        self._last_update[voice] = now
