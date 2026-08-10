from __future__ import annotations

import argparse
import asyncio  # noqa: ANYIO_OK
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True, slots=True)
class _Installed:
    voices: list[str]
    skills: list[str]


def _install_pack(*, source: str, config_dir: Path, force: bool) -> _Installed:
    """Clone-or-pull a pack (git URL or local path) and copy voices/ + skills/ in.

    A pack is a dir tree with `voices/<id>/SOUL.md` and `skills/<name>/SKILL.md`.
    Those layouts are already consumed by create_voice() and _ensure_voice_skills(),
    so copying them into config_dir is the whole job. Copy-missing unless --force.
    """
    src_path = Path(source)
    if src_path.exists():
        pack_dir = src_path.resolve()
    else:
        # ponytail: git URL → clone into cache, pull if present. No new dep.
        cache = Path.home() / ".cache" / "kateto" / "packs" / Path(source).stem.replace(".git", "")
        if cache.is_dir():
            subprocess.run(["git", "-C", str(cache), "pull", "--ff-only"], check=False)
            pack_dir = cache
        else:
            cache.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--depth", "1", source, str(cache)], check=True)
            pack_dir = cache

    installed_voices: list[str] = []
    installed_skills: list[str] = []
    for kind, sink in (("voices", installed_voices), ("skills", installed_skills)):
        src = pack_dir / kind
        if not src.is_dir():
            continue
        dst = config_dir / kind
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if not item.is_dir():
                continue
            target = dst / item.name
            if target.exists() and not force:
                continue
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
            sink.append(item.name)
    return _Installed(voices=installed_voices, skills=installed_skills)


class Install(Command):
    """Install a voice/skill pack from a git repo or local path."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("source", help="git URL or local path to a pack")
        _ = parser.add_argument("--force", action="store_true", help="overwrite existing voices/skills")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        source = str(getattr(parsed_args, "source"))
        force = bool(getattr(parsed_args, "force", False))
        try:
            loaded = load_config()
        except _CONFIG_ERRORS as error:
            _ = self.app.stderr.write(f"install: {error}\n")
            return 2
        try:
            result = _install_pack(source=source, config_dir=loaded.paths.config_dir, force=force)
        except (subprocess.CalledProcessError, OSError) as error:
            _ = self.app.stderr.write(f"install: {error}\n")
            return 2
        if not result.voices and not result.skills:
            _ = self.app.stdout.write("install: nothing installed (pack has no voices/ or skills/)\n")
            return 0
        for name in result.voices:
            _ = self.app.stdout.write(f"installed voice: {name}\n")
        for name in result.skills:
            _ = self.app.stdout.write(f"installed skill: {name}\n")
        return 0


register_command("config check", ConfigCheck)
register_command("run", Run)
register_command("smoke", Smoke)
register_command("tui", Tui)
register_command("install", Install)
