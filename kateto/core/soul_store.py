from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar, cast


class SoulSnapshotBackend(Protocol):
    def snapshot(self, voice: str, key: str, content: str) -> None: ...
    def rollback(self, voice: str, key: str) -> str | None: ...


_T = TypeVar("_T")
_Root = dict[str, list[str]]


class ZodBackend:
    """Snapshot history stored in a ZODB object database.

    One FileStorage per voice (POSIX record locks are per-process, so a
    shared file would deadlock in-process); root maps key -> stack of
    previous SOUL/JOURNAL contents. Writes commit transactionally, so a
    crash never leaves a half-applied snapshot.
    """

    def __init__(self, config_dir: Path, *, max_depth: int = 10) -> None:
        from ZODB.FileStorage import FileStorage
        import ZODB
        import transaction
        from persistent.list import PersistentList

        self._FileStorage: Any = FileStorage
        self._ZODB: Any = ZODB
        self._transaction: Any = transaction
        self._PersistentList: Any = PersistentList
        self._state_dir = config_dir / "state"
        self._max_depth = max_depth

    def snapshot(self, voice: str, key: str, content: str) -> None:
        def _do(root: _Root) -> None:
            stack = root[key] if key in root else self._PersistentList()
            stack.append(content)
            while len(stack) > self._max_depth:
                stack.pop(0)
            root[key] = stack

        self._with_root(voice, _do)

    def rollback(self, voice: str, key: str) -> str | None:
        def _do(root: _Root) -> str | None:
            stack = root.get(key)
            if not stack:
                return None
            previous = stack.pop()
            if not stack:
                del root[key]
            return previous

        return self._with_root(voice, _do)

    def _with_root(self, voice: str, operation: Callable[[_Root], _T]) -> _T:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self._state_dir / f"soul_snapshots_{voice}.fs"
        storage = self._FileStorage(str(path))
        db = self._ZODB.DB(storage)
        try:
            connection = db.open()
            try:
                root = cast(_Root, connection.root())
                result = operation(root)
            finally:
                self._transaction.commit()
                connection.close()
            return result
        finally:
            db.close()
            storage.close()


class JsonlAuditBackend:
    """Append-only JSONL audit log of snapshots; rollback replays the last one."""

    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / "state" / "soul_audit.jsonl"

    def snapshot(self, voice: str, key: str, content: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "voice": voice,
            "key": key,
            "action": "snapshot",
            "previous": content,
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def rollback(self, voice: str, key: str) -> str | None:
        if not self._path.is_file():
            return None
        snapshots: list[str] = []
        rollbacks = 0
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                entry = json.loads(line)
                if entry.get("voice") != voice or entry.get("key") != key:
                    continue
                if entry.get("action") == "snapshot":
                    snapshots.append(entry.get("previous", ""))
                elif entry.get("action") == "rollback":
                    rollbacks += 1
        if rollbacks >= len(snapshots):
            return None
        previous = snapshots[-(rollbacks + 1)]
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "voice": voice,
            "key": key,
            "action": "rollback",
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return previous


def open_soul_snapshot_store(config_dir: Path, *, backend: str = "zodb") -> SoulSnapshotBackend:
    if backend == "zodb":
        try:
            return ZodBackend(config_dir)
        except ImportError:
            pass
    return JsonlAuditBackend(config_dir)
