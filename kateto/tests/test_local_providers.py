from __future__ import annotations

import pytest

from kateto.core.config import PluginSettings
from kateto.core.exceptions import ProviderError
from kateto.providers import LocalClassifierProvider, LocalWhisperProvider
from kateto.providers._local import _first_json, _read_whisper_json


def test_plugin_settings_loads_command_and_args() -> None:
    settings = PluginSettings(command="x")
    assert settings.command == "x"
    settings = PluginSettings(command="whisper-cli", args=["-t", "4"])
    assert settings.args == ["-t", "4"]
    assert PluginSettings().command is None
    assert PluginSettings().args is None


def test_local_providers_require_command() -> None:
    with pytest.raises(ProviderError):
        LocalWhisperProvider(PluginSettings())
    with pytest.raises(ProviderError):
        LocalClassifierProvider(PluginSettings())


def test_local_providers_construct_with_command() -> None:
    settings = PluginSettings(command="whisper-cli", model="model.gguf", args=["-t", "4"])
    whisper = LocalWhisperProvider(settings)
    assert whisper._command == "whisper-cli"
    assert whisper._model == "model.gguf"
    classifier = LocalClassifierProvider(settings)
    assert classifier._argv("-p", "hi") == ["whisper-cli", "-p", "hi", "-t", "4"]


def test_first_json_extracts_dict() -> None:
    assert _first_json('prefix {"a": 1} suffix') == {"a": 1}
    assert _first_json('{"a": {"b": 2}}') == {"a": {"b": 2}}
    assert _first_json("no json here") is None


def test_read_whisper_json_reads_first_existing_file(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text('{"text": "hola"}')
    assert _read_whisper_json([first, second]) == {"text": "hola"}
