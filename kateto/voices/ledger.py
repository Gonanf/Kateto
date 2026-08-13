from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, field_validator

from kateto.core.soul_store import SoulSnapshotBackend, open_soul_snapshot_store
from kateto.core.storage import atomic_write_text

_DEPT_NAME: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")

MAX_FACT_CHARS: Final = 400
MAX_EVIDENCE_CHARS: Final = 500
MAX_ENTRIES: Final = 200
BLOCK_MAX_ENTRIES: Final = 40
BLOCK_MAX_EVIDENCE_CHARS: Final = 100

_LEDGER_LOCKS: dict[Path, asyncio.Lock] = {}


class MemoryCategory(StrEnum):
    facts = "facts"
    relationships = "relationships"
    action_patterns = "action_patterns"


class MemoryEntry(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    fact: str
    category: MemoryCategory
    evidence: str = ""
    created_at: str
    updated_at: str

    @field_validator("fact")
    @classmethod
    def _fact_must_be_nonempty_and_bounded(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("fact must not be empty")
        if len(normalized) > MAX_FACT_CHARS:
            raise ValueError(f"fact too long (>{MAX_FACT_CHARS} chars)")
        return normalized

    @field_validator("evidence")
    @classmethod
    def _evidence_must_be_bounded(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) > MAX_EVIDENCE_CHARS:
            raise ValueError(f"evidence too long (>{MAX_EVIDENCE_CHARS} chars)")
        return normalized


class VoiceMemoryLedger:
    """Typed, department-scoped memory store for voices.

    One JSON document per department (``config_dir/memory/{dept}.json``): all
    voices in ``fun`` share stream memory; ``work``/``management`` voices share
    project memory. Every mutation snapshots the previous document into the
    existing SoulSnapshotStore (ZODB), validates the resulting entries with
    Pydantic, and only then writes atomically under a per-file asyncio lock.
    If validation or the write fails, the snapshot is rolled back (the disk
    document was never touched).
    """

    def __init__(
        self,
        config_dir: Path,
        dept: str,
        *,
        snapshots: SoulSnapshotBackend | None = None,
    ) -> None:
        resolved = config_dir.resolve()
        if _DEPT_NAME.fullmatch(dept) is None:
            raise ValueError(f"invalid department name: {dept!r}")
        self._config_dir: Path = resolved
        self._dept: str = dept
        self._path: Path = resolved / "memory" / f"{dept}.json"
        self._snapshots: SoulSnapshotBackend = (
            snapshots if snapshots is not None else open_soul_snapshot_store(resolved)
        )

    @classmethod
    def for_dept(cls, *, config_dir: Path, dept: str) -> VoiceMemoryLedger:
        return cls(config_dir=config_dir, dept=dept)

    def _lock(self) -> asyncio.Lock:
        resolved = self._path.resolve()
        lock = _LEDGER_LOCKS.get(resolved)
        if lock is None:
            lock = asyncio.Lock()
            _LEDGER_LOCKS[resolved] = lock
        return lock

    # ponytail: process-wide lock dict mirrors core/storage.py; per-dept locks
    # are enough because a dept file is only ever touched through this module.

    def _read_raw(self) -> str:
        if not self._path.is_file():
            return ""
        return self._path.read_text(encoding="utf-8")

    def _load(self) -> list[MemoryEntry]:
        raw = self._read_raw().strip()
        if not raw:
            return []
        return [MemoryEntry(**entry) for entry in json.loads(raw)]

    async def _write(self, entries: list[MemoryEntry]) -> None:
        payload = json.dumps(
            [entry.model_dump() for entry in entries],
            ensure_ascii=False,
            indent=2,
        )
        await atomic_write_text(self._path, payload)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def render_block(self) -> str:
        """Compact `<VOICE_MEMORY>` block; empty string when the ledger is empty.

        Renders the most recently touched entries so the injected block stays
        stable and small. Facts are kept whole (substring replace depends on
        them); evidence is truncated for display only.
        """
        entries = self._load()
        if not entries:
            return ""
        recent = sorted(entries, key=lambda entry: entry.updated_at, reverse=True)[:BLOCK_MAX_ENTRIES]
        lines = ["<VOICE_MEMORY>"]
        for category in MemoryCategory:
            group = [entry for entry in recent if entry.category is category]
            if not group:
                continue
            lines.append(f"{category.value}:")
            for entry in group:
                line = f"- {entry.fact}"
                if entry.evidence:
                    evidence = entry.evidence
                    if len(evidence) > BLOCK_MAX_EVIDENCE_CHARS:
                        evidence = evidence[:BLOCK_MAX_EVIDENCE_CHARS].rstrip() + "\u2026"
                    line += f" ({evidence})"
                lines.append(line)
        lines.append("</VOICE_MEMORY>")
        return "\n".join(lines)

    @staticmethod
    def _find_unique(entries: list[MemoryEntry], category: MemoryCategory, needle: str) -> int | None:
        matches = [
            index
            for index, entry in enumerate(entries)
            if entry.category is category and needle in entry.fact.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous match for {needle!r}: {len(matches)} entries; use a longer substring"
            )
        return None

    @staticmethod
    def _bound(entries: list[MemoryEntry]) -> list[MemoryEntry]:
        if len(entries) > MAX_ENTRIES:
            entries = sorted(entries, key=lambda entry: entry.updated_at, reverse=True)[:MAX_ENTRIES]
        return entries

    def _upsert(self, entries: list[MemoryEntry], category: MemoryCategory, fact: str, evidence: str) -> str:
        now = self._now()
        folded = fact.casefold()
        for index, entry in enumerate(entries):
            if entry.category is category and entry.fact.casefold() == folded:
                entries[index] = entry.model_copy(update={"evidence": evidence, "updated_at": now})
                return "replaced"
        if evidence:
            index = self._find_unique(entries, category, evidence.casefold())
            if index is not None:
                entries[index] = entries[index].model_copy(
                    update={"fact": fact, "evidence": evidence, "updated_at": now}
                )
                return "replaced"
            # no match -> add below, recording the evidence
        entries.append(
            MemoryEntry(fact=fact, category=category, evidence=evidence, created_at=now, updated_at=now)
        )
        entries[:] = self._bound(entries)
        return "added"

    def _remove(self, entries: list[MemoryEntry], category: MemoryCategory, needle: str) -> str:
        index = self._find_unique(entries, category, needle.casefold())
        if index is None:
            raise ValueError(f"no {category.value} entry contains {needle!r}")
        del entries[index]
        return "removed"

    async def refine(self, *, fact: str, category: str, evidence: str = "") -> dict[str, object]:
        """Add, replace, or remove one memory entry.

        ``category`` must be one of MemoryCategory values. ``fact`` is the
        declarative fact to store; empty fact removes (``evidence`` carries the
        unique substring identifying the entry). Non-empty ``evidence`` inside a
        replacement locates the entry to update by a short unique substring of
        its current fact.
        """
        category_enum = MemoryCategory(category)
        fact = " ".join(fact.split())
        evidence = " ".join(evidence.split())
        if not fact and not evidence:
            return {
                "action": "unchanged",
                "category": category_enum.value,
                "fact": "",
                "error": "nothing to store or remove: fact and evidence are both empty",
            }
        async with self._lock():
            before = self._read_raw()
            self._snapshots.snapshot(self._dept, "ledger", before)
            try:
                entries = self._load()
                if fact:
                    action = self._upsert(entries, category_enum, fact, evidence)
                else:
                    action = self._remove(entries, category_enum, evidence)
                await self._write(entries)
            except Exception:
                # Validation or write failure: restore the pre-mutation snapshot.
                self._snapshots.rollback(self._dept, "ledger")
                raise
        return {
            "action": action,
            "category": category_enum.value,
            "fact": fact or evidence,
            "entries": len(entries),
        }

    async def rollback(self) -> str | None:
        """Restore the document to the state before the last mutation."""
        previous = self._snapshots.rollback(self._dept, "ledger")
        if previous is not None:
            await atomic_write_text(self._path, previous)
        return previous

    def entries(self, *, category: str | None = None) -> list[dict[str, object]]:
        """Read path for tests/tools: validated entries as plain dicts."""
        entries = self._load()
        if category is not None:
            wanted = MemoryCategory(category)
            entries = [entry for entry in entries if entry.category is wanted]
        return [entry.model_dump() for entry in entries]