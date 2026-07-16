from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import CliSettings
from kateto.core.event import BacklogAddData, BacklogStatus, TodoItemData
from kateto.plugins.connector.cli import (
    CliArgumentRejectedError,
    CliCommandData,
    CliConnector,
    CliReplyData,
    CliReplyStatus,
    CommandResult,
    normalize_argv,
)


class ReplySink(Plugin):
    def __init__(self) -> None:
        super().__init__("cli_reply_sink")
        self.replies: list[CliReplyData] = []

    async def on_cli_reply(self, data: CliReplyData) -> None:
        self.replies.append(data)


class BacklogSink(Plugin):
    def __init__(self) -> None:
        super().__init__("backlog_sink")
        self.additions: list[BacklogAddData] = []

    async def on_backlog_add(self, data: BacklogAddData) -> None:
        self.additions.append(data)


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    async def run(self, argv: tuple[str, ...], *, working_directory: Path) -> CommandResult:
        self.calls.append((argv, working_directory))
        return CommandResult(returncode=0, stdout=b"fixture stdout\n", stderr=b"fixture stderr\n")


class HangingRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, argv: tuple[str, ...], *, working_directory: Path) -> CommandResult:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("hung runner unexpectedly returned")


@pytest.mark.asyncio
async def test_cli_connector_normalizes_allowlisted_argv_and_emits_captured_reply(tmp_path: Path) -> None:
    # Given: an enabled connector and a reply target with echo in its configured allowlist.
    manager = PluginManager()
    connector = CliConnector(settings=CliSettings(allowlist=["echo"]), working_directory=tmp_path)
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        # When: a spaced allowlisted command reaches the connector event boundary.
        await manager.emit(
            "cli_execute",
            CliCommandData(command="  echo    kateto  ", reply_to=sink.name, timeout_seconds=1),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: a direct-exec reply preserves normalized argv and exact process streams.
        assert sink.replies == [
            CliReplyData(
                argv=("echo", "kateto"),
                stdout="kateto\n",
                stderr="",
                returncode=0,
                status=CliReplyStatus.COMPLETED,
            ),
        ]
        reply_envelope = next(event for event in manager.get_events() if event.name == "cli_reply")
        assert reply_envelope.target == sink.name
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    (
        "rm -rf /tmp/x",
        "/bin/echo kateto",
        "echo /tmp/x",
        "echo ..",
        "echo $(id)",
        "echo 'unterminated",
    ),
)
async def test_cli_connector_rejects_untrusted_command_text_before_runner_spawn(command: str, tmp_path: Path) -> None:
    # Given: a connector whose injected runner records every process-spawn request.
    runner = RecordingRunner()
    manager = PluginManager()
    connector = CliConnector(
        settings=CliSettings(allowlist=["echo"]),
        runner=runner,
        working_directory=tmp_path,
    )
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        # When: a disallowed executable, path, shell-shaped argument, or malformed argv arrives.
        await manager.emit(
            "cli_execute",
            CliCommandData(command=command, reply_to=sink.name, timeout_seconds=1),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: it is rejected as typed data without spawning an external process.
        assert runner.calls == []
        assert len(sink.replies) == 1
        assert sink.replies[0].status is CliReplyStatus.REJECTED
        assert sink.replies[0].returncode is None
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    (
        "git config --global user.name kateto",
        "git config --system user.name kateto",
        "git config --file=.. user.name kateto",
        "git --git-dir=.. status",
    ),
)
async def test_cli_connector_rejects_global_and_external_config_options_before_runner_spawn(
    command: str,
    tmp_path: Path,
) -> None:
    # Given: git remains configured as an allowed executable but its runner records spawn requests.
    runner = RecordingRunner()
    manager = PluginManager()
    connector = CliConnector(
        settings=CliSettings(allowlist=["git"]),
        runner=runner,
        working_directory=tmp_path,
    )
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        # When: a command selects a global or alternate configuration location.
        await manager.emit(
            "cli_execute",
            CliCommandData(command=command, reply_to=sink.name, timeout_seconds=1),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: the configuration-writing request is rejected before the allowed executable can run.
        assert runner.calls == []
        assert [reply.status for reply in sink.replies] == [CliReplyStatus.REJECTED]
    finally:
        await manager.close()


def test_normalize_argv_rejects_a_bare_symlink_that_resolves_outside_working_directory(tmp_path: Path) -> None:
    # Given: a configured working directory containing a name that resolves outside its boundary.
    outside_directory = tmp_path.parent / "outside"
    outside_directory.mkdir()
    (tmp_path / "outside-link").symlink_to(outside_directory, target_is_directory=True)

    # When / Then: an allowlisted command tries to use that bare path as a working-directory argument.
    with pytest.raises(CliArgumentRejectedError):
        normalize_argv(
            "git -C outside-link status",
            settings=CliSettings(allowlist=["git"]),
            working_directory=tmp_path,
        )
    assert normalize_argv(
        "git status",
        settings=CliSettings(allowlist=["git"]),
        working_directory=tmp_path,
    ) == ("git", "status")


@pytest.mark.asyncio
async def test_cli_connector_times_out_hung_runner_and_records_typed_timeout(tmp_path: Path) -> None:
    # Given: an allowlisted command backed by a runner that never completes.
    runner = HangingRunner()
    manager = PluginManager()
    connector = CliConnector(
        settings=CliSettings(allowlist=["echo"]),
        runner=runner,
        working_directory=tmp_path,
    )
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        # When: its bounded timeout expires.
        await manager.emit(
            "cli_execute",
            CliCommandData(command="echo kateto", reply_to=sink.name, timeout_seconds=0.01),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: cancellation reaches the runner and a timeout reply is observable.
        assert runner.started.is_set()
        assert runner.cancelled.is_set()
        assert [reply.status for reply in sink.replies] == [CliReplyStatus.TIMED_OUT]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cli_connector_repeated_interrupts_cancel_hung_runner_once(tmp_path: Path) -> None:
    # Given: a live command whose runner cannot complete without cancellation.
    runner = HangingRunner()
    manager = PluginManager()
    connector = CliConnector(
        settings=CliSettings(allowlist=["echo"]),
        runner=runner,
        working_directory=tmp_path,
    )
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        await manager.emit(
            "cli_execute",
            CliCommandData(command="echo kateto", reply_to=sink.name, timeout_seconds=1),
            source="fixture",
        )
        await runner.started.wait()

        # When: two targeted interruption events arrive while the child is hung.
        await manager.interrupt(target=connector.name, reason="new-speech")
        await manager.interrupt(target=connector.name, reason="repeat")
        await manager.wait_for_idle()

        # Then: one cancellation is delivered and the connector returns a typed cancellation reply.
        assert runner.cancelled.is_set()
        assert [reply.status for reply in sink.replies] == [CliReplyStatus.CANCELLED]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_cli_connector_syncs_completed_todo_once_through_canonical_backlog_event(tmp_path: Path) -> None:
    # Given: the connector and a canonical backlog event subscriber.
    manager = PluginManager()
    connector = CliConnector(settings=CliSettings(allowlist=["echo"]), working_directory=tmp_path)
    backlog = BacklogSink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(backlog)
    completed = TodoItemData(voice="doktor", task="ship connector", completed=True)
    try:
        # When: the same completed TODO event is delivered twice.
        await manager.emit("todo_completed", completed, source="executor_todo_list")
        await manager.emit("todo_completed", completed, source="executor_todo_list")
        await manager.wait_for_idle()

        # Then: exactly one canonical Done backlog-add event represents the completed TODO.
        assert len(backlog.additions) == 1
        item = backlog.additions[0].item
        assert item.title == "ship connector"
        assert item.status is BacklogStatus.DONE
        assert item.created_by == "todo:doktor"
        assert item.tags == ["todo", "completed"]
    finally:
        await manager.close()


def test_cli_fixture_reports_real_success_and_pre_spawn_rejection() -> None:
    # Given: the user-facing QA wrapper at its documented repository-root invocation.
    command = [sys.executable, "scripts/qa/cli_fixture.py", "--command"]

    # When: an allowlisted echo and a rejected destructive command are run through it.
    success = subprocess.run([*command, "echo kateto"], capture_output=True, check=False, text=True)
    rejected = subprocess.run([*command, "rm -rf /tmp/x"], capture_output=True, check=False, text=True)

    # Then: output is machine-readable, exact stdout is preserved, and rejection occurs before spawn.
    success_reply = json.loads(next(line.removeprefix("CLI_REPLY ") for line in success.stdout.splitlines() if line.startswith("CLI_REPLY ")))
    rejected_reply = json.loads(next(line.removeprefix("CLI_REPLY ") for line in rejected.stdout.splitlines() if line.startswith("CLI_REPLY ")))
    assert success.returncode == 0, success.stderr
    assert success_reply["stdout"] == "kateto\n"
    assert success_reply["status"] == "completed"
    assert "SPAWN_COUNT 1" in success.stdout
    assert rejected.returncode == 2, rejected.stderr
    assert rejected_reply["status"] == "rejected"
    assert "SPAWN_COUNT 0" in rejected.stdout
