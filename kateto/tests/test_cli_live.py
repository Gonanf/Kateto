from __future__ import annotations

import subprocess
import sys

import pytest

from kateto import __main__ as cli


def test_help_exposes_the_live_run_path() -> None:
    # Given: the installed module entry point.
    command = [sys.executable, "-m", "kateto"]

    # When: a user asks for top-level and run-specific help.
    top_level = subprocess.run([*command, "--help"], capture_output=True, check=False, text=True)
    run_help = subprocess.run([*command, "run", "--help"], capture_output=True, check=False, text=True)

    # Then: help makes the live run path discoverable without starting hardware or providers.
    assert top_level.returncode == 0, top_level.stderr
    assert "kateto run" in top_level.stdout
    assert run_help.returncode == 0, run_help.stderr
    assert "usage: kateto run" in run_help.stdout


def test_run_dispatches_to_the_live_runner_without_a_fixture_substitute(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a live runner probe and a configuration loader probe.
    calls: list[str] = []

    def load_config_probe() -> str:
        return "configured-live"

    async def run_live_probe(config: str) -> None:
        calls.append(config)

    monkeypatch.setattr(cli, "load_config", load_config_probe)
    monkeypatch.setattr(cli, "run_live", run_live_probe)
    monkeypatch.setattr(sys, "argv", ["kateto", "run"])

    # When: the non-fixture run command is invoked.
    result = cli.main()

    # Then: only the configured live runner receives control.
    assert result == 0
    assert calls == ["configured-live"]
