from __future__ import annotations

import asyncio
import fcntl
import json
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from kateto.core.event import (
    BacklogAddData,
    BacklogItem,
    BacklogListData,
    BacklogUpdateData,
    EventModel,
)
from kateto.core.plugin import Plugin
from kateto.core.storage import atomic_write_text


_BACKLOG_LOCKS: dict[Path, asyncio.Lock] = {}
_BACKLOG_FILE_NAME: Final = "product_backlog.json"


@dataclass(slots=True)
class BacklogStorageError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"backlog store is invalid at {self.path}: {self.reason}"


@dataclass(slots=True)
class BacklogValidationError(Exception):
    reason: str

    def __str__(self) -> str:
        return f"invalid backlog request: {self.reason}"


@dataclass(slots=True)
class BacklogItemNotFoundError(Exception):
    item_id: str

    def __str__(self) -> str:
        return f"backlog item was not found: {self.item_id}"


@dataclass(slots=True)
class BacklogDuplicateItemError(Exception):
    item_id: str

    def __str__(self) -> str:
        return f"backlog item already exists: {self.item_id}"


class BacklogAddedData(EventModel):
    item: BacklogItem


class BacklogUpdatedData(EventModel):
    item: BacklogItem


class BacklogListedData(EventModel):
    items: list[BacklogItem]


class BacklogErrorData(EventModel):
    operation: str
    code: str
    message: str


def _lock_for(path: Path) -> asyncio.Lock:
    resolved_path = path.resolve()
    existing_lock = _BACKLOG_LOCKS.get(resolved_path)
    if existing_lock is not None:
        return existing_lock
    created_lock = asyncio.Lock()
    _BACKLOG_LOCKS[resolved_path] = created_lock
    return created_lock


def _acquire_process_lock(path: Path) -> int:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _release_process_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class _ProcessLockLease:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._descriptor: int | None = None
        self._closed = False

    def hold(self, descriptor: int) -> bool:
        with self._guard:
            if self._closed:
                return False
            self._descriptor = descriptor
            return True

    def release(self) -> None:
        with self._guard:
            self._closed = True
            descriptor = self._descriptor
            self._descriptor = None
        if descriptor is not None:
            _release_process_lock(descriptor)


def _acquire_process_lock_for_lease(path: Path, lease: _ProcessLockLease) -> None:
    descriptor = _acquire_process_lock(path)
    if not lease.hold(descriptor):
        _release_process_lock(descriptor)


@asynccontextmanager
async def _transaction_lock(path: Path) -> AsyncIterator[None]:
    async with _lock_for(path):
        lease = _ProcessLockLease()
        try:
            await asyncio.to_thread(_acquire_process_lock_for_lease, path, lease)
            yield
        finally:
            lease.release()


class BacklogOwner(Plugin):
    def __init__(self, *, backlog_path: Path) -> None:
        if backlog_path.name != _BACKLOG_FILE_NAME:
            raise BacklogValidationError(reason=f"canonical file must be {_BACKLOG_FILE_NAME}")
        super().__init__("backlog", capabilities=("backlog",))
        self._backlog_path = backlog_path.resolve()

    async def initialize(self) -> None:
        if self.manager is None:
            raise RuntimeError("backlog owner requires a plugin manager")
        self.manager.register_event("backlog_list", BacklogListData)
        self.manager.register_event("backlog_add", BacklogAddData)
        self.manager.register_event("backlog_update", BacklogUpdateData)
        self.manager.register_event("backlog_listed", BacklogListedData)
        self.manager.register_event("backlog_added", BacklogAddedData)
        self.manager.register_event("backlog_updated", BacklogUpdatedData)
        self.manager.register_event("backlog_error", BacklogErrorData)

    async def list_items(self, filters: BacklogListData) -> tuple[BacklogItem, ...]:
        validated_filters = self._validate_list(filters)
        async with _transaction_lock(self._backlog_path):
            items = self._read_items()
        return tuple(
            item
            for item in items
            if (validated_filters.status is None or item.status is validated_filters.status)
            and (validated_filters.priority is None or item.priority is validated_filters.priority)
        )

    async def add_item(self, item: BacklogItem) -> BacklogItem:
        validated_item = self._validate_item(item)
        async with _transaction_lock(self._backlog_path):
            items = self._read_items()
            if any(existing.id == validated_item.id for existing in items):
                raise BacklogDuplicateItemError(item_id=validated_item.id)
            await self._write_items((*items, validated_item))
        return validated_item

    async def update_item(self, update: BacklogUpdateData) -> BacklogItem:
        validated_update = self._validate_update(update)
        changes = validated_update.model_dump(exclude={"id"}, exclude_unset=True)
        if not changes:
            raise BacklogValidationError(reason="at least one mutable field is required")
        async with _transaction_lock(self._backlog_path):
            items = self._read_items()
            updated_items: list[BacklogItem] = []
            updated_item: BacklogItem | None = None
            for item in items:
                if item.id == validated_update.id:
                    updated_item = self._validate_item(item.model_copy(update=changes))
                    updated_items.append(updated_item)
                else:
                    updated_items.append(item)
            if updated_item is None:
                raise BacklogItemNotFoundError(item_id=validated_update.id)
            await self._write_items(tuple(updated_items))
        return updated_item

    async def on_backlog_list(self, data: BacklogListData) -> None:
        try:
            items = await self.list_items(data)
        except (BacklogStorageError, BacklogValidationError) as error:
            await self._emit_error(operation="list", error=error)
            return
        await self._manager_emit("backlog_listed", BacklogListedData(items=list(items)))

    async def on_backlog_add(self, data: BacklogAddData) -> None:
        try:
            validated_data = self._validate_add(data)
            item = await self.add_item(validated_data.item)
        except (BacklogDuplicateItemError, BacklogStorageError, BacklogValidationError) as error:
            await self._emit_error(operation="add", error=error)
            return
        await self._manager_emit("backlog_added", BacklogAddedData(item=item))

    async def on_backlog_update(self, data: BacklogUpdateData) -> None:
        try:
            item = await self.update_item(data)
        except (BacklogItemNotFoundError, BacklogStorageError, BacklogValidationError) as error:
            await self._emit_error(operation="update", error=error)
            return
        await self._manager_emit("backlog_updated", BacklogUpdatedData(item=item))

    def _read_items(self) -> tuple[BacklogItem, ...]:
        if not self._backlog_path.exists():
            return ()
        try:
            contents = self._backlog_path.read_text(encoding="utf-8")
        except OSError as error:
            raise BacklogStorageError(path=self._backlog_path, reason="unreadable") from error
        try:
            raw_items = json.loads(contents)
        except json.JSONDecodeError as error:
            raise BacklogStorageError(path=self._backlog_path, reason="malformed JSON") from error
        if not isinstance(raw_items, list):
            raise BacklogStorageError(path=self._backlog_path, reason="expected a JSON array")
        try:
            return tuple(BacklogItem.model_validate(raw_item) for raw_item in raw_items)
        except ValidationError as error:
            raise BacklogStorageError(path=self._backlog_path, reason="invalid item schema") from error

    async def _write_items(self, items: tuple[BacklogItem, ...]) -> None:
        contents = json.dumps(
            [item.model_dump(mode="json") for item in items],
            ensure_ascii=False,
            indent=2,
        )
        await atomic_write_text(self._backlog_path, f"{contents}\n")

    def _validate_list(self, data: BacklogListData) -> BacklogListData:
        try:
            return BacklogListData.model_validate(
                data.model_dump(mode="python", exclude_unset=True, warnings="none"),
            )
        except ValidationError as error:
            raise BacklogValidationError(reason="invalid list filters") from error

    def _validate_add(self, data: BacklogAddData) -> BacklogAddData:
        try:
            return BacklogAddData.model_validate(
                data.model_dump(mode="python", exclude_unset=True, warnings="none"),
            )
        except ValidationError as error:
            raise BacklogValidationError(reason="invalid add item") from error

    def _validate_item(self, item: BacklogItem) -> BacklogItem:
        try:
            return BacklogItem.model_validate(
                item.model_dump(mode="python", exclude_unset=True, warnings="none"),
            )
        except ValidationError as error:
            raise BacklogValidationError(reason="invalid backlog item") from error

    def _validate_update(self, data: BacklogUpdateData) -> BacklogUpdateData:
        try:
            return BacklogUpdateData.model_validate(
                data.model_dump(mode="python", exclude_unset=True, warnings="none"),
            )
        except ValidationError as error:
            raise BacklogValidationError(reason="invalid update") from error

    async def _manager_emit(self, event_name: str, data: EventModel) -> None:
        if self.manager is None:
            raise RuntimeError("backlog owner requires a plugin manager")
        await self.manager.emit(event_name, data, source=self.name)

    async def _emit_error(self, *, operation: str, error: Exception) -> None:
        await self._manager_emit(
            "backlog_error",
            BacklogErrorData(
                operation=operation,
                code=type(error).__name__,
                message=str(error),
            ),
        )
