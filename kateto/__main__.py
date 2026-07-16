from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import sys
import subprocess
from pathlib import Path
from typing import Final

from kateto.core.config import (
    ConfigBootstrapError,
    ConfigPathError,
    ConfigReadError,
    ConfigTomlError,
    ConfigValidationError,
    load_config,
)
from kateto.live import LiveAssemblyConfigurationError
from kateto.plugins.system.tui import run_tui
from kateto.run_mode import run_live

_USAGE: Final = "usage: kateto [-h] | kateto config check | kateto run | kateto smoke --fixture | kateto tui [--fixture]\n"
_RUN_USAGE: Final = "usage: kateto run\n"
_CONFIG_ERRORS: Final = (
    ConfigBootstrapError,
    ConfigPathError,
    ConfigReadError,
    ConfigTomlError,
    ConfigValidationError,
)


def main() -> int:
    match sys.argv[1:]:
        case [] | ["-h"] | ["--help"]:
            print(_USAGE, end="")
            return 0
        case ["config", "check"]:
            return _check_config()
        case ["run", "-h"] | ["run", "--help"]:
            print(_RUN_USAGE, end="")
            return 0
        case ["run"]:
            return _run_live()
        case ["smoke", "--fixture"]:
            evidence = Path.cwd() / ".omo" / "evidence" / "kateto-mvp" / "recovery" / "smoke-cleanup"
            return subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "qa" / "acceptance.py"), "--fixture", "--evidence-dir", str(evidence)],
                check=False,
            ).returncode
        case ["tui"]:
            run_tui()
            return 0
        case ["tui", "--fixture"]:
            run_tui(fixture=True)
            return 0
        case _:
            print(_USAGE, end="", file=sys.stderr)
            return 2


def _check_config() -> int:
    try:
        loaded = load_config()
    except _CONFIG_ERRORS as error:
        print(f"config check: {error}", file=sys.stderr)
        return 2
    print(f"config check: ok ({loaded.paths.config_dir})")
    return 0


def _run_live() -> int:
    try:
        loaded = load_config()
        asyncio.run(run_live(loaded))
    except (*_CONFIG_ERRORS, LiveAssemblyConfigurationError) as error:
        print(f"run: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
