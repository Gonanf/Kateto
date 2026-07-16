# /// script
# requires-python = ">=3.12"
# ///

# ─── How to run ───
# uv run python scripts/qa/cli_fixture.py --command 'echo kateto'
# ──────────────────

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from kateto.core import Plugin, PluginManager
from kateto.core.config import CliSettings
from kateto.plugins.connector.cli import CliCommandData, CliConnector, CliReplyData, CliReplyStatus, CommandResult, SubprocessCommandRunner


class ReplySink(Plugin):
    def __init__(self) -> None:
        super().__init__("cli_fixture_reply")
        self.reply: CliReplyData | None = None

    async def on_cli_reply(self, data: CliReplyData) -> None:
        self.reply = data


class CountingRunner:
    def __init__(self) -> None:
        self.spawn_count = 0
        self._delegate = SubprocessCommandRunner()

    async def run(self, argv: tuple[str, ...], *, working_directory: Path) -> CommandResult:
        self.spawn_count += 1
        return await self._delegate.run(argv, working_directory=working_directory)


@dataclass(frozen=True, slots=True)
class FixtureResult:
    reply: CliReplyData
    spawn_count: int


async def run_fixture(command: str, timeout_seconds: float) -> FixtureResult:
    manager = PluginManager()
    runner = CountingRunner()
    connector = CliConnector(
        settings=CliSettings(allowlist=["cat", "date", "echo", "git", "ls", "pwd"]),
        runner=runner,
        working_directory=Path.cwd(),
    )
    sink = ReplySink()
    await manager.enable_plugin(connector)
    await manager.enable_plugin(sink)
    try:
        await manager.emit(
            "cli_execute",
            CliCommandData(command=command, reply_to=sink.name, timeout_seconds=timeout_seconds),
            source="cli_fixture",
        )
        await manager.wait_for_idle()
        if sink.reply is None:
            raise RuntimeError("CLI fixture did not receive a reply")
        return FixtureResult(reply=sink.reply, spawn_count=runner.spawn_count)
    finally:
        await manager.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True)
    parser.add_argument("--timeout", type=float, default=1.0)
    arguments = parser.parse_args()
    result = asyncio.run(run_fixture(arguments.command, arguments.timeout))
    print("CLI_REPLY " + json.dumps(result.reply.model_dump(mode="json"), separators=(",", ":"), sort_keys=True))
    print(f"SPAWN_COUNT {result.spawn_count}")
    return 0 if result.reply.status is CliReplyStatus.COMPLETED else 2


if __name__ == "__main__":
    raise SystemExit(main())
