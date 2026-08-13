from __future__ import annotations

from pathlib import Path


class VoiceUpdater:
    """SOUL/JOURNAL maintenance shell (disabled by the memory-ledger feature).

    SOUL.md and JOURNAL.md are no longer mutated mid-session: declarative
    memories go to the per-department VoiceMemoryLedger through the
    refine_memory tool, and the SOUL only changes between sessions via
    versioned snapshots (SoulSnapshotStore). Methods are kept as no-ops so
    the plugin surface stays stable.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    async def append_idle_entry(self, voice: str) -> None:
        # ponytail: journal hot-writes removed; idle events are not
        # declarative memory (hygiene rule), so nothing is recorded mid-session.
        return None

    async def touch_soul(self, voice: str) -> None:
        # ponytail: SOUL is read-only mid-session; it only changes between
        # sessions via versioned snapshots.
        return None