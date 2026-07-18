from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import hashlib
import os
import shlex
import shutil
import signal
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath, PureWindowsPath
from typing import Final

from pydantic import BaseModel, Field

from kateto.core.config import ConfigError, CliSettings, validate_cli_command
from kateto.core.event import BacklogAddData, BacklogItem, BacklogPriority, BacklogStatus, EventEnvelope, EventModel, InterruptData, TodoItemData
from kateto.core.manager import PluginManager
from kateto.core.plugin import EventHandler, Plugin
from kateto.core.manager import PluginManager


_SHELL_CONTROL_CHARACTERS: Final[frozenset[str]] = frozenset(";&|<>`$!\r\n\x00")
_TODO_TAGS: Final[tuple[str, ...]] = ("todo", "completed")


@dataclass(frozen=True, slots=True)
class CliArgumentRejectedError(Exception):
    reason: str

    def __str__(self) -> str:
        return f"cli argument rejected: {self.reason}"


@dataclass(frozen=True, slots=True)
class CliExecutableMissingError(Exception):
    executable: str

    def __str__(self) -> str:
        return f"configured cli executable is unavailable: {self.executable}"


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CliReplyStatus(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CliCommandData(EventModel):
    command: str = Field(min_length=1)
    reply_to: str | None = Field(default=None, min_length=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)


class CliReplyData(EventModel):
    argv: tuple[str, ...] = ()
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    status: CliReplyStatus
    reason: str | None = None


class SubprocessCommandRunner:
    async def run(self, argv: tuple[str, ...], *, working_directory: Path) -> CommandResult:
        executable = shutil.which(argv[0], path=os.defpath)
        if executable is None:
            raise CliExecutableMissingError(executable=argv[0])
        process = await asyncio.create_subprocess_exec(
            executable,
            *argv[1:],
            cwd=working_directory,
            env={"LC_ALL": "C", "PATH": os.defpath},
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            await _terminate_process(process)
            raise
        return CommandResult(returncode=await process.wait(), stdout=stdout, stderr=stderr)


class CliConnector(Plugin):
    def __init__(
        self,
        *,
        settings: CliSettings,
        runner: SubprocessCommandRunner | None = None,
        working_directory: Path | None = None,
    ) -> None:
        super().__init__("connector_cli")
        self._settings = CliSettings(allowlist=list(settings.allowlist))
        self._runner = SubprocessCommandRunner() if runner is None else runner
        self._working_directory = (Path.cwd() if working_directory is None else working_directory).resolve()
        self._active_task: asyncio.Task[None] | None = None
        self._interruption_requested = False
        self._synced_todo_ids: set[str] = set()

    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("cli_execute", CliCommandData)
        manager.register_event("cli_reply", CliReplyData)
        manager.register_event("todo_completed", TodoItemData)
        manager.register_event("backlog_add", BacklogAddData)

    async def _enqueue(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case _:
                await super()._enqueue(envelope, handler)

    async def on_cli_execute(self, data: CliCommandData) -> None:
        argv: tuple[str, ...] = ()
        active_task = asyncio.current_task()
        if active_task is not None:
            self._active_task = active_task
        try:
            try:
                argv = normalize_argv(data.command, settings=self._settings, working_directory=self._working_directory)
            except (ConfigError, CliArgumentRejectedError) as error:
                await self._emit_reply(
                    CliReplyData(argv=argv, status=CliReplyStatus.REJECTED, reason=str(error)),
                    reply_to=data.reply_to,
                )
                return
            try:
                result = await asyncio.wait_for(
                    self._runner.run(argv, working_directory=self._working_directory),
                    timeout=data.timeout_seconds,
                )
            except TimeoutError:
                reply = CliReplyData(argv=argv, status=CliReplyStatus.TIMED_OUT, reason="command exceeded timeout")
            except (CliExecutableMissingError, OSError) as error:
                reply = CliReplyData(argv=argv, status=CliReplyStatus.FAILED, reason=str(error))
            else:
                reply = CliReplyData(
                    argv=argv,
                    stdout=result.stdout.decode("utf-8", errors="replace"),
                    stderr=result.stderr.decode("utf-8", errors="replace"),
                    returncode=result.returncode,
                    status=CliReplyStatus.COMPLETED,
                )
            await self._emit_reply(reply, reply_to=data.reply_to)
        except asyncio.CancelledError:
            await self._emit_reply(
                CliReplyData(argv=argv, status=CliReplyStatus.CANCELLED, reason="command interrupted"),
                reply_to=data.reply_to,
            )
            raise
        finally:
            if self._active_task is active_task:
                self._active_task = None
                self._interruption_requested = False

    async def on_interrupt(self, data: InterruptData) -> None:
        active_task = self._active_task
        if active_task is not None and not active_task.done() and not self._interruption_requested:
            self._interruption_requested = True
            active_task.cancel()

    async def on_todo_completed(self, data: TodoItemData) -> None:
        if not data.completed:
            return
        item = _backlog_item_for(data)
        if item.id in self._synced_todo_ids:
            return
        self._synced_todo_ids.add(item.id)
        try:
            await self._manager().emit("backlog_add", BacklogAddData(item=item), source=self.name)
        except asyncio.CancelledError:
            self._synced_todo_ids.discard(item.id)
            raise

    async def _emit_reply(self, reply: CliReplyData, *, reply_to: str | None) -> None:
        await self._manager().emit("cli_reply", reply, source=self.name, target=reply_to)

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            raise RuntimeError("CLI connector must be enabled before use")
        return manager


def normalize_argv(command: str, *, settings: CliSettings, working_directory: Path) -> tuple[str, ...]:
    try:
        argv = tuple(shlex.split(command, posix=True))
    except ValueError as error:
        raise CliArgumentRejectedError(reason="malformed argv") from error
    normalized = validate_cli_command(argv, settings=settings)
    resolved_working_directory = working_directory.resolve()
    for argument in normalized[1:]:
        _validate_argument(argument, working_directory=resolved_working_directory)
    return normalized


def _validate_argument(argument: str, *, working_directory: Path) -> None:
    if any(character in argument for character in _SHELL_CONTROL_CHARACTERS) or argument.startswith("~"):
        raise CliArgumentRejectedError(reason="shell syntax is not permitted")
    if argument.startswith("-"):
        raise CliArgumentRejectedError(reason="command options are not permitted")
    posix_path = PurePath(argument)
    windows_path = PureWindowsPath(argument)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        raise CliArgumentRejectedError(reason="path escapes connector working directory")
    resolved = (working_directory / posix_path).resolve()
    if not resolved.is_relative_to(working_directory):
        raise CliArgumentRejectedError(reason="path escapes connector working directory")


def _backlog_item_for(data: TodoItemData) -> BacklogItem:
    digest = hashlib.sha256(f"{data.voice}\x00{data.task.casefold()}".encode()).hexdigest()[:16]
    return BacklogItem(
        id=f"todo-{digest}",
        title=data.task,
        description=f"Completed TODO from {data.voice}",
        priority=BacklogPriority.SHOULD,
        status=BacklogStatus.DONE,
        created_by=f"todo:{data.voice}",
        tags=list(_TODO_TAGS),
    )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
    await process.communicate()
