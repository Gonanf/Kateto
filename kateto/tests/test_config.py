from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kateto.core.config import (
    ConfigTomlError,
    ConfigValidationError,
    bootstrap_config,
    load_config,
)


_MINIMAL_CONFIG = """\
[kateto]
debug = false
hot_reload = false

[cli]
allowlist = ["ls"]
"""


def _write_config(config_dir: Path, contents: str) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(contents, encoding="utf-8")
    return config_path


def test_bootstrap_copies_default_tree_on_first_run(tmp_path: Path) -> None:
    # Given: an empty config home and a versioned default tree.
    defaults_dir = tmp_path / "defaults"
    default_config = _write_config(defaults_dir, _MINIMAL_CONFIG)
    default_voice_asset = defaults_dir / "voices" / "Jane" / "workflow.toml"
    default_voice_asset.parent.mkdir(parents=True)
    default_voice_asset.write_text("name = 'daily'\n", encoding="utf-8")
    config_dir = tmp_path / "config-home" / "kateto"

    # When: bootstrap runs for the first time.
    paths = bootstrap_config(config_dir=config_dir, defaults_dir=defaults_dir)

    # Then: the complete default tree becomes the user's initial config tree.
    assert paths.config_file.read_text(encoding="utf-8") == default_config.read_text(encoding="utf-8")
    assert (config_dir / "voices" / "Jane" / "workflow.toml").read_text(encoding="utf-8") == "name = 'daily'\n"


def test_bootstrap_preserves_existing_config_after_default_changes(tmp_path: Path) -> None:
    # Given: a config copied on an earlier run and newer packaged defaults.
    defaults_dir = tmp_path / "defaults"
    _write_config(defaults_dir, _MINIMAL_CONFIG)
    config_dir = tmp_path / "config-home" / "kateto"
    bootstrap_config(config_dir=config_dir, defaults_dir=defaults_dir)
    existing_config = config_dir / "config.toml"
    existing_config.write_text(_MINIMAL_CONFIG.replace("false", "true", 1), encoding="utf-8")
    _write_config(defaults_dir, _MINIMAL_CONFIG.replace('allowlist = ["ls"]', 'allowlist = ["date"]'))

    # When: bootstrap runs again after the packaged defaults change.
    bootstrap_config(config_dir=config_dir, defaults_dir=defaults_dir)

    # Then: the user's existing config is never overwritten by a stale copy.
    assert "debug = true" in existing_config.read_text(encoding="utf-8")
    assert 'allowlist = ["ls"]' in existing_config.read_text(encoding="utf-8")


def test_load_config_accepts_canonical_sections_and_keeps_env_secret_out_of_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: canonical sections, a local asset, and an environment-only secret.
    config_dir = tmp_path / "kateto"
    asset_path = config_dir / "voices" / "jane" / "reference.wav"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(b"fixture-wav")
    _write_config(
        config_dir,
        """\
[kateto]
debug = false
hot_reload = false

[plugin.audio_processor_transcription]
enabled = true
endpoint = "http://localhost:8081"

[voice.jane]
enabled = true
reference_audio = "voices/jane/reference.wav"
skills = ["orchestrator"]

[mcp_servers.fixture]
command = "uvx"
args = ["fixture-server"]

[cli]
allowlist = ["ls", "pwd"]
""",
    )
    (config_dir / ".env").write_text("OPENAI_API_KEY=fixture-secret\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # When: the config boundary parses the TOML and loads its .env file.
    loaded = load_config(config_dir=config_dir)

    # Then: typed settings retain endpoints/assets but never serialize the secret.
    assert loaded.settings.plugin["audio_processor_transcription"].endpoint == "http://localhost:8081"
    assert loaded.settings.voice["jane"].reference_audio == "voices/jane/reference.wav"
    assert os.environ["OPENAI_API_KEY"] == "fixture-secret"
    assert "fixture-secret" not in loaded.settings.model_dump_json()


def test_load_config_rejects_malformed_toml(tmp_path: Path) -> None:
    # Given: an invalid TOML config file.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, "[kateto\ndebug = false\n")

    # When: the config boundary parses it.
    with pytest.raises(ConfigTomlError, match="malformed TOML"):
        load_config(config_dir=config_dir)


def test_load_config_rejects_unknown_setting_with_its_path(tmp_path: Path) -> None:
    # Given: an otherwise canonical config with a misspelled setting.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG.replace("hot_reload = false", "hot_reload = false\nunknown = true"))

    # When: schema validation runs.
    with pytest.raises(ConfigValidationError, match=r"kateto\.unknown"):
        load_config(config_dir=config_dir)


@pytest.mark.parametrize(
    ("extra_section", "rejected_setting"),
    [
        (
            """\
[plugin.audio_processor_transcription]
endpoint = "file:///etc/passwd"
""",
            "plugin.audio_processor_transcription.endpoint",
        ),
        (
            """\
[voice.jane]
reference_audio = "../outside.wav"
""",
            "voice.jane.reference_audio",
        ),
    ],
)
def test_load_config_rejects_invalid_endpoint_or_asset_path(
    tmp_path: Path,
    extra_section: str,
    rejected_setting: str,
) -> None:
    # Given: a config that attempts to escape its allowed endpoint or asset boundary.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG + "\n" + extra_section)

    # When: settings are parsed.
    with pytest.raises(ConfigValidationError, match=rejected_setting):
        load_config(config_dir=config_dir)


def test_load_config_rejects_disallowed_cli_command_with_setting_name(tmp_path: Path) -> None:
    # Given: a config that tries to allow destructive shell execution.
    config_dir = tmp_path / "kateto"
    _write_config(config_dir, _MINIMAL_CONFIG.replace('allowlist = ["ls"]', 'allowlist = ["rm"]'))

    # When: CLI allowlist validation runs.
    with pytest.raises(ConfigValidationError) as captured:
        load_config(config_dir=config_dir)

    # Then: the failure names both the rejected setting and command.
    assert "cli.allowlist" in str(captured.value)
    assert "rm" in str(captured.value)


def test_config_check_cli_bootstraps_xdg_tree(tmp_path: Path) -> None:
    # Given: a fresh XDG config home.
    config_home = tmp_path / "xdg"
    environment = os.environ.copy()
    environment["XDG_CONFIG_HOME"] = str(config_home)
    environment.pop("APPDATA", None)

    # When: a user checks the config through the shipped CLI.
    completed_process = subprocess.run(
        [sys.executable, "-m", "kateto", "config", "check"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    # Then: the tree exists and the real command reports a safe success message.
    assert completed_process.returncode == 0, completed_process.stderr
    assert (config_home / "kateto" / "config.toml").is_file()
    assert "config check: ok" in completed_process.stdout
