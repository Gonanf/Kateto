from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kateto.core.storage import VoiceFileStore


SOUL_WORD_LIMIT: Final = 500
JOURNAL_ENTRY_LIMIT: Final = 50
JOURNAL_TOKEN_LIMIT: Final = 3_000
MEMORIES_WORD_LIMIT: Final = 1_000


@dataclass(frozen=True, slots=True)
class VoiceMemory:
    store: VoiceFileStore

    @classmethod
    def for_voice(cls, *, config_dir: Path, voice: str) -> VoiceMemory:
        return cls(store=VoiceFileStore.for_voice(config_dir=config_dir, voice=voice))

    async def read_soul(self) -> str:
        return self._read("SOUL.md")

    async def read_journal(self) -> str:
        return self._read("JOURNAL.md")

    async def read_memories(self) -> str:
        return self._read("MEMORIES.md")

    async def ensure_soul(self, default_soul: str) -> str:
        existing = await self.read_soul()
        selected = existing if existing.strip() else default_soul
        await self.write_soul(selected)
        return await self.read_soul()

    async def write_soul(self, soul: str) -> None:
        await self.store.write_text("SOUL.md", _first_words(soul, SOUL_WORD_LIMIT))

    async def append_journal(self, entry: str) -> None:
        existing_entries = tuple(line.strip() for line in (await self.read_journal()).splitlines() if line.strip())
        normalized_entry = " ".join(entry.split())
        entries = (*existing_entries, normalized_entry) if normalized_entry else existing_entries
        bounded_entries = entries[-JOURNAL_ENTRY_LIMIT:]
        while len(bounded_entries) > 1 and _token_count("\n".join(bounded_entries)) > JOURNAL_TOKEN_LIMIT:
            bounded_entries = bounded_entries[1:]
        if bounded_entries and _token_count("\n".join(bounded_entries)) > JOURNAL_TOKEN_LIMIT:
            bounded_entries = (_last_words(bounded_entries[-1], JOURNAL_TOKEN_LIMIT),)
        await self.store.write_text("JOURNAL.md", "\n".join(bounded_entries))

    async def append_memories(self, memory: str) -> None:
        combined = " ".join((await self.read_memories()).split() + memory.split())
        await self.store.write_text("MEMORIES.md", _last_words(combined, MEMORIES_WORD_LIMIT))

    def _read(self, filename: str) -> str:
        path = self.store.path_for(filename)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")


def _first_words(value: str, limit: int) -> str:
    return " ".join(value.split()[:limit])


def _last_words(value: str, limit: int) -> str:
    return " ".join(value.split()[-limit:])


def _token_count(value: str) -> int:
    return len(value.split())
