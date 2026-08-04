from __future__ import annotations

import argparse
import asyncio  # noqa: ANYIO_OK
import subprocess
import sys
from typing import override

from cliff.command import Command

from kateto.cli.registry import register_command
from kateto.core.config import load_config
from kateto.core.discovery import LiveAssemblyConfigurationError as EventRuntimeConfigurationError
from kateto.core.exceptions import ConfigError
from kateto.plugins.system.tui import run_tui
from kateto.run_mode import run_event_runtime

_CONFIG_ERRORS: tuple[type[Exception], ...] = (ConfigError,)


class ConfigCheck(Command):
    """Validate the kateto configuration."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        try:
            loaded = load_config()
        except _CONFIG_ERRORS as error:
            _ = self.app.stderr.write(f"config check: {error}\n")
            return 2
        _ = self.app.stdout.write(f"config check: ok ({loaded.paths.config_dir})\n")
        return 0


class Run(Command):
    """Run the event runtime."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        try:
            loaded = load_config()
            asyncio.run(run_event_runtime(loaded))
        except (*_CONFIG_ERRORS, EventRuntimeConfigurationError) as error:
            _ = self.app.stderr.write(f"run: {error}\n")
            return 2
        return 0


class Smoke(Command):
    """Run the bounded smoke test suite."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("--fixture", action="store_true", help="use deterministic fixtures")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        # ponytail: smoke runs the core test suite instead of the
        # deleted scripts/qa/acceptance.py.  Add a dedicated e2e
        # runner when a full bounded smoke is needed.
        return subprocess.run(            [sys.executable, "-m", "pytest",
             "kateto/tests/test_event_bus.py", "kateto/tests/test_plugin_manager.py",
             "kateto/tests/test_config.py", "kateto/tests/test_workflow.py",
             "kateto/tests/test_storage.py", "-q"],
            check=False,
        ).returncode


class Tui(Command):
    """Run the terminal UI."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("--fixture", action="store_true", help="use deterministic fixtures")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        run_tui(fixture=bool(getattr(parsed_args, "fixture", False)))
        return 0


register_command("config check", ConfigCheck)
register_command("run", Run)
register_command("smoke", Smoke)
register_command("tui", Tui)
