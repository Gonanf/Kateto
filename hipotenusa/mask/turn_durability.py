from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

MIB = 1024 * 1024
DEFAULT_MAX_FRAMES = 512
DEFAULT_MAX_BYTES = 4 * MIB
RESUME_MESSAGE_TYPE = "mask_resume"
RESUME_EVENT = "audio_resume"


@dataclass(frozen=True)
class ResumeBatch:
    after_seq: int
    frames: list[dict[str, Any]]   # payloads con seq > after_seq, ascendente por seq
    gap: bool                      # True si after_seq < first_seq - 1 (se evictaron frames)
    turn_id: int                   # turn_id del último frame retenido (0 si vacío)


class TurnJournal:
    def __init__(self, *, max_frames: int = DEFAULT_MAX_FRAMES, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self._frames: deque[tuple[dict[str, Any], int]] = deque()
        self._total_bytes: int = 0
        self._current_seq: int = 0
        self._current_turn_id: int = 0
        self._pending_turn_advance: bool = False
        self._dropped: int = 0
        self._turns_started: int = 0

    def stamp(self, payload: dict[str, Any], *, final: bool, n_bytes: int = 0) -> dict[str, Any]:
        """Devuelve un dict NUEVO (copia de payload) con seq y turn_id agregados y lo appendea al ring.

        No muta payload. Si final: el PRÓXIMO stamp sube turn_id.
        """
        if self._current_turn_id == 0:
            self._current_turn_id = 1
            self._turns_started = 1
            self._pending_turn_advance = False
        elif self._pending_turn_advance:
            self._current_turn_id += 1
            self._turns_started += 1
            self._pending_turn_advance = False

        self._current_seq += 1
        stamped = dict(payload)
        stamped["seq"] = self._current_seq
        stamped["turn_id"] = self._current_turn_id

        if final:
            self._pending_turn_advance = True

        if n_bytes == 0 and isinstance(payload.get("audio"), str):
            n_bytes = len(payload["audio"])

        self._frames.append((stamped, n_bytes))
        self._total_bytes += n_bytes

        while self._frames and (len(self._frames) > self.max_frames or self._total_bytes > self.max_bytes):
            _, dropped_bytes = self._frames.popleft()
            self._total_bytes -= dropped_bytes
            self._dropped += 1

        return stamped

    def resume(self, after_seq: int) -> ResumeBatch:
        """Frames retenidos con seq > after_seq.

        after_seq <= 0 => todos los retenidos, gap=False.
        gap = after_seq < (first_seq - 1) cuando hay frames retenidos; si el ring está vacío,
        frames=[] y gap=False.
        """
        if not self._frames:
            return ResumeBatch(after_seq=after_seq, frames=[], gap=False, turn_id=0)

        frames = [f for f, _ in self._frames if f["seq"] > after_seq]
        gap = False
        if after_seq > 0:
            first_seq = self._frames[0][0]["seq"]
            gap = after_seq < (first_seq - 1)

        turn_id = self._frames[-1][0]["turn_id"]
        return ResumeBatch(after_seq=after_seq, frames=frames, gap=gap, turn_id=turn_id)

    @property
    def first_seq(self) -> int | None:
        return self._frames[0][0]["seq"] if self._frames else None

    @property
    def last_seq(self) -> int | None:
        return self._frames[-1][0]["seq"] if self._frames else None

    @property
    def turn_id(self) -> int:
        return self._current_turn_id

    def stats(self) -> dict[str, int]:
        return {
            "frames": len(self._frames),
            "bytes": self._total_bytes,
            "dropped": self._dropped,
            "turns_started": self._turns_started,
        }

    def clear(self) -> None:
        self._frames.clear()
        self._total_bytes = 0
        self._current_seq = 0
        self._current_turn_id = 0
        self._pending_turn_advance = False
        self._dropped = 0
        self._turns_started = 0


@dataclass
class TurnDurabilityMetrics:
    turns_started: int = 0
    turns_survived: int = 0
    turns_lost: int = 0
    disconnects: int = 0
    resumes: int = 0
    replayed_frames: int = 0
    gaps: int = 0

    def start_turn(self) -> None:
        self.turns_started += 1

    def finish_turn(self, *, survived: bool) -> None:
        if survived:
            self.turns_survived += 1
        else:
            self.turns_lost += 1

    def disconnect(self) -> None:
        self.disconnects += 1

    def resume(self, *, replayed: int = 0, gap: bool = False) -> None:
        self.resumes += 1
        self.replayed_frames += replayed
        if gap:
            self.gaps += 1

    @property
    def survived_pct(self) -> float:
        if self.turns_started == 0:
            return 0.0
        return 100.0 * self.turns_survived / self.turns_started

    def snapshot(self) -> dict[str, Any]:
        return {
            "turns_started": self.turns_started,
            "turns_survived": self.turns_survived,
            "turns_lost": self.turns_lost,
            "disconnects": self.disconnects,
            "resumes": self.resumes,
            "replayed_frames": self.replayed_frames,
            "gaps": self.gaps,
            "survived_pct": round(self.survived_pct, 1),
        }
