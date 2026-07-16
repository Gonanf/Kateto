from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from kateto.core.event import Classification, ClassificationData, TodoItemData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin, PluginManagerProtocol
from kateto.core.storage import VoiceFileStore


_CREATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?:plan|todo|task|remember)\s+(.+)$", re.IGNORECASE)
_COMPLETE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?:complete|done|finish)\s+(?:todo\s+)?(.+)$", re.IGNORECASE)
_TODO_LINE: Final[re.Pattern[str]] = re.compile(r"^- \[([ x])\] (.+)$")
_SHARED_VOICE: Final[str] = "shared"


@dataclass(frozen=True, slots=True)
class TodoEntry:
    task: str
    completed: bool


@dataclass(frozen=True, slots=True)
class CreateTodo:
    task: str


@dataclass(frozen=True, slots=True)
class CompleteTodo:
    task: str


type TodoAction = CreateTodo | CompleteTodo


class TodoListExecutor(Plugin):
    def __init__(self, *, config_dir: Path, voice: str | None = None) -> None:
        super().__init__("executor_todo_list")
        store_voice = _SHARED_VOICE if voice is None else voice
        self._store = VoiceFileStore.for_voice(config_dir=config_dir, voice=store_voice)

    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("classification", ClassificationData)
        manager.register_event("todo_updated", TodoItemData)
        manager.register_event("todo_completed", TodoItemData)

    async def on_classification(self, data: ClassificationData) -> None:
        match data.category:
            case Classification.EXECUTE:
                action = _parse_action(data.text)
                if action is not None:
                    await self._apply(action)
            case Classification.IGNORE_SELF_TALK | Classification.IGNORE_THIRD_PARTY:
                return
            case unreachable:
                assert_never(unreachable)

    async def _apply(self, action: TodoAction) -> None:
        entries = self._read_entries()
        match action:
            case CreateTodo(task=task):
                if any(entry.task.casefold() == task.casefold() for entry in entries):
                    return
                updated_entries = (*entries, TodoEntry(task=task, completed=False))
                await self._write_entries(updated_entries)
                await self._emit("todo_updated", task, completed=False)
            case CompleteTodo(task=task):
                updated_entries, changed = _complete(entries, task)
                if not changed:
                    return
                await self._write_entries(updated_entries)
                await self._emit("todo_updated", task, completed=True)
                await self._emit("todo_completed", task, completed=True)
            case unreachable:
                assert_never(unreachable)

    def _read_entries(self) -> tuple[TodoEntry, ...]:
        path = self._store.path_for("TODO.md")
        if not path.is_file():
            return ()
        entries: list[TodoEntry] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _TODO_LINE.fullmatch(line)
            if match is None:
                continue
            entries.append(TodoEntry(task=match.group(2), completed=match.group(1) == "x"))
        return tuple(entries)

    async def _write_entries(self, entries: tuple[TodoEntry, ...]) -> None:
        lines = ["# TODO", ""]
        lines.extend(f"- [{'x' if entry.completed else ' '}] {entry.task}" for entry in entries)
        await self._store.write_text("TODO.md", "\n".join(lines) + "\n")

    async def _emit(self, event_name: str, task: str, *, completed: bool) -> None:
        await self._manager().emit(
            event_name,
            TodoItemData(voice=self._store.voice, task=task, completed=completed),
            source=self.name,
        )

    def _manager(self) -> PluginManagerProtocol:
        manager = self.manager
        if manager is None:
            msg = "TODO executor must be enabled before use"
            raise RuntimeError(msg)
        return manager


def _parse_action(text: str) -> TodoAction | None:
    normalized = " ".join(text.split())
    complete_match = _COMPLETE_PATTERN.fullmatch(normalized)
    if complete_match is not None:
        return CompleteTodo(task=complete_match.group(1))
    create_match = _CREATE_PATTERN.fullmatch(normalized)
    if create_match is not None:
        return CreateTodo(task=create_match.group(1))
    return None


def _complete(entries: tuple[TodoEntry, ...], task: str) -> tuple[tuple[TodoEntry, ...], bool]:
    completed = False
    updated_entries: list[TodoEntry] = []
    for entry in entries:
        if entry.task.casefold() == task.casefold() and not entry.completed:
            updated_entries.append(TodoEntry(task=entry.task, completed=True))
            completed = True
        else:
            updated_entries.append(entry)
    return tuple(updated_entries), completed
