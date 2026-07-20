from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from kateto.voices.memory import VoiceMemory


class VoiceUpdater:
    """Read/write SOUL.md and JOURNAL.md for a voice via VoiceMemory."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir

    async def append_idle_entry(self, voice: str) -> None:
        """Append an idle-timestamp line to the voice's JOURNAL.md."""
        memory = VoiceMemory.for_voice(config_dir=self._config_dir, voice=voice)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        await memory.append_journal(f"[auto] voice_idle at {timestamp}")

    async def touch_soul(self, voice: str) -> None:
        """Ensure SOUL.md exists and carries a last_active marker.

        If the soul is empty, write a minimal one. If non-empty, append or
        update a ``last_active:`` line so the voice's personality file
        reflects recency without overwriting user/agent-authored content.
        """
        memory = VoiceMemory.for_voice(config_dir=self._config_dir, voice=voice)
        soul = await memory.read_soul()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not soul.strip():
            await memory.write_soul(f"# {voice} SOUL\n\n> last_active: {now}\n")
            return
        lines = soul.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("> last_active:"):
                lines[i] = f"> last_active: {now}"
                await memory.write_soul("\n".join(lines))
                return
        await memory.write_soul(soul + f"\n> last_active: {now}")
