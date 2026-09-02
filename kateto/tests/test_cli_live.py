from __future__ import annotations

import subprocess
import sys

import pytest

from kateto import __main__ as cli
from kateto.cli import commands as cli_commands


def test_help_exposes_the_event_runtime_path() -> None:
    # Given: the installed module entry point.
    command = [sys.executable, "-m", "kateto"]

    # When: a user asks for top-level and run-specific help.
    top_level = subprocess.run([*command, "--help"], capture_output=True, check=False, text=True)
    run_help = subprocess.run([*command, "run", "--help"], capture_output=True, check=False, text=True)

    # Then: help makes the live run path discoverable without starting hardware or providers.
    assert top_level.returncode == 0, top_level.stderr
    assert "run" in top_level.stdout
    assert "config check" in top_level.stdout
    assert run_help.returncode == 0, run_help.stderr
    assert "usage: kateto run" in run_help.stdout


def test_run_dispatches_to_the_event_runtime_without_a_fixture_substitute(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a live runner probe and a configuration loader probe.
    calls: list[str] = []

    def load_config_probe() -> str:
        return "configured-live"

    async def run_event_runtime_probe(config: str, **_: object) -> None:
        calls.append(config)

    monkeypatch.setattr(cli_commands, "load_config", load_config_probe)
    monkeypatch.setattr(cli_commands, "run_event_runtime", run_event_runtime_probe)
    monkeypatch.setattr(sys, "argv", ["kateto", "run"])

    # When: the non-fixture run command is invoked.
    result = cli.main()

    # Then: only the configured live runner receives control.
    assert result == 0
    assert calls == ["configured-live"]


def test_real_provider_factory_reads_plugin_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a loaded configuration where voice_llm is a PluginSettings instance.
    from unittest.mock import MagicMock
    from kateto.core.config import PluginSettings

    fake_config = MagicMock()
    fake_config.settings.plugin = {
        "voice_llm": PluginSettings(
            model="Kateto",
            endpoint="http://127.0.0.1:11434/v1",
            api_key="sk-test-key",
        )
    }
    monkeypatch.setattr(cli_commands, "load_config", lambda: fake_config)
    monkeypatch.delenv("KATETO_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("KATETO_LLM_MODEL", raising=False)
    monkeypatch.delenv("KATETO_LLM_API_KEY", raising=False)

    # When: the provider factory is created.
    factory = cli_commands._real_provider_factory()
    provider = factory("jane")

    # Then: it resolves the model, endpoint, and api_key configured in PluginSettings.
    assert provider.model == "Kateto"
    assert provider.endpoint == "http://127.0.0.1:11434/v1"
    assert provider.api_key == "sk-test-key"


def test_real_provider_factory_default_model_is_kateto(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: no config and no env vars.
    from unittest.mock import MagicMock

    fake_config = MagicMock()
    fake_config.settings.plugin = {}
    monkeypatch.setattr(cli_commands, "load_config", lambda: fake_config)
    monkeypatch.delenv("KATETO_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("KATETO_LLM_MODEL", raising=False)
    monkeypatch.delenv("KATETO_LLM_API_KEY", raising=False)

    # When: factory is created.
    factory = cli_commands._real_provider_factory()
    provider = factory("jane")

    # Then: model defaults to Kateto, not KatetoTalker.
    assert provider.model == "Kateto"
    assert provider.endpoint == "http://localhost:11434/v1"
