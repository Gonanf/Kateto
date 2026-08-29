from __future__ import annotations

import argparse
import asyncio  # noqa: ANYIO_OK
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import override

from cliff.command import Command

from kateto.cli.agency_convert import _resolve_source, convert_agency_pack
from kateto.cli.registry import register_command
from kateto.core.config import load_config
from kateto.core.discovery import LiveAssemblyConfigurationError as EventRuntimeConfigurationError
from kateto.core.exceptions import ConfigError
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
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("--trace", action="store_true", help="log every bus event to stderr")
        _ = parser.add_argument("--trace-events", metavar="NAME", action="append", default=[], help="only trace events with this name (repeatable)")
        _ = parser.add_argument("--trace-voice", metavar="VOICE", action="append", default=[], help="only trace events touching this voice (repeatable)")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        trace = bool(getattr(parsed_args, "trace", False))
        trace_events = tuple(str(event) for event in getattr(parsed_args, "trace_events", ()))
        trace_voice = tuple(str(voice) for voice in getattr(parsed_args, "trace_voice", ()))
        try:
            loaded = load_config()
            asyncio.run(
                run_event_runtime(
                    loaded,
                    trace=trace,
                    trace_events=trace_events,
                    trace_voice=trace_voice,
                )
            )
        except (*_CONFIG_ERRORS, EventRuntimeConfigurationError) as error:
            _ = self.app.stderr.write(f"run: {error}\n")
            return 2
        return 0


class Smoke(Command):
    """Run the bounded smoke test suite."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        return subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "kateto/tests/test_event_bus.py", "kateto/tests/test_plugin_manager.py",
                "kateto/tests/test_config.py", "kateto/tests/test_workflow.py",
                "kateto/tests/test_storage.py", "-q",
            ],
            check=False,
        ).returncode


class Compile(Command):
    """Install and compile pywhispercpp / llama-cpp-python bindings with chosen acceleration."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument(
            "target",
            choices=["whisper", "llama", "all"],
            default="all",
            nargs="?",
            help="target to install: whisper, llama, or all (default: all)",
        )
        _ = parser.add_argument(
            "--backend",
            choices=["vulkan", "cuda", "cpu", "metal", "openblas"],
            default="vulkan",
            help="hardware acceleration backend (default: vulkan)",
        )
        _ = parser.add_argument(
            "--cmake-args",
            action="append",
            default=[],
            help="extra CMake arguments (repeatable)",
        )
        _ = parser.add_argument(
            "--jobs",
            type=int,
            default=1,
            help="maximum parallel compiler jobs to prevent OOM (default: 1, max: 2)",
        )
        _ = parser.add_argument(
            "--no-prebuilt",
            action="store_true",
            help="force source compilation instead of using prebuilt wheels",
        )
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        from kateto.tools.compiler import CompilerOptions, compile_llama, compile_whisper

        target = str(getattr(parsed_args, "target", "all"))
        backend = str(getattr(parsed_args, "backend", "vulkan"))
        cmake_args = [str(arg) for arg in getattr(parsed_args, "cmake_args", [])]
        jobs = int(getattr(parsed_args, "jobs", 1))
        prefer_prebuilt = not bool(getattr(parsed_args, "no_prebuilt", False))

        opts = CompilerOptions(
            backend=backend,
            cmake_args=cmake_args,
            jobs=jobs,
            prefer_prebuilt=prefer_prebuilt,
        )

        code = 0
        if target in ("whisper", "all"):
            code = compile_whisper(opts)
            if code != 0:
                return code
        if target in ("llama", "all"):
            code = compile_llama(opts)
            if code != 0:
                return code
        return code


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
    pack_dir = _resolve_source(source, cache_root=Path.home() / ".cache" / "kateto" / "packs")

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
    """Install a voice/skill pack, or convert an agency-agents repo with --from-agency."""

    @override
    def get_parser(self, prog_name: str) -> argparse.ArgumentParser:
        parser = super().get_parser(prog_name)
        _ = parser.add_argument("source", help="git URL or local path to a pack (or agency-agents repo with --from-agency)")
        _ = parser.add_argument("--force", action="store_true", help="overwrite existing voices/skills")
        _ = parser.add_argument("--from-agency", action="store_true", help="treat source as an agency-agents repo (division dirs of .md agents)")
        return parser

    @override
    def take_action(self, parsed_args: object) -> int:
        source = str(getattr(parsed_args, "source"))
        force = bool(getattr(parsed_args, "force", False))
        from_agency = bool(getattr(parsed_args, "from_agency", False))
        try:
            loaded = load_config()
        except _CONFIG_ERRORS as error:
            _ = self.app.stderr.write(f"install: {error}\n")
            return 2
        try:
            if from_agency:
                repo_dir = _resolve_source(source, cache_root=Path.home() / ".cache" / "kateto" / "agency")
                with tempfile.TemporaryDirectory(prefix="kateto-agency-") as tmp:
                    converted = convert_agency_pack(repo_dir, Path(tmp), force=force)
                    if not converted:
                        _ = self.app.stdout.write("install: no agency agents converted\n")
                        return 0
                    result = _install_pack(source=tmp, config_dir=loaded.paths.config_dir, force=force)
            else:
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


class Setup(Command):
    """Interactively configure models/endpoints (deep-merge, secrets to file)."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        from kateto.cli.setup_wizard import run_setup

        try:
            return run_setup()
        except (KeyboardInterrupt, EOFError):
            _ = self.app.stderr.write("setup: aborted\n")
            return 1


class Doctor(Command):
    """Report config, models, servers, VAD and masked API keys."""

    @override
    def take_action(self, parsed_args: object) -> int:
        del parsed_args
        from dotenv import load_dotenv

        from kateto.cli.doctor import doctor_report
        from kateto.core.config import resolve_config_dir

        config_dir = resolve_config_dir()
        _ = load_dotenv(dotenv_path=config_dir / ".env", override=False)
        _ = load_dotenv(dotenv_path=config_dir / "secrets" / ".env", override=False)
        config_file = config_dir / "config.toml"
        config_text = config_file.read_text() if config_file.is_file() else None
        exit_code, results = doctor_report(config_text)
        for result in results:
            status = "ok" if result.ok else "FAIL"
            _ = self.app.stdout.write(f"[{status}] {result.name}: {result.detail}\n")
        return exit_code


register_command("config check", ConfigCheck)
register_command("run", Run)
register_command("smoke", Smoke)
register_command("compile", Compile)
register_command("install", Install)
register_command("setup", Setup)
register_command("doctor", Doctor)
