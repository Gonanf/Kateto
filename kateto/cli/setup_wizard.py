from __future__ import annotations

import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kateto.core.config import default_config_dir, resolve_config_dir


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        # ponytail: inline tables only; nested [[array]] tables (none used)
        # would need a real TOML writer.
        body = ", ".join(f"{key} = {_toml_value(child)}" for key, child in value.items())
        return f"{{ {body} }}"
    raise ValueError(f"unsupported TOML value: {value!r}")


def dumps_toml(raw: Mapping[str, Any]) -> str:
    lines: list[str] = []
    for group, table in raw.items():
        if not isinstance(table, dict):
            continue
        lines.append(f"[{group}]")
        for key, value in table.items():
            if isinstance(value, dict):
                # ponytail: nested tables as dotted keys; full [[array]] tables
                # (none used) would need a real TOML writer.
                for subkey, subvalue in value.items():
                    lines.append(f"{key}.{subkey} = {_toml_value(subvalue)}")
            else:
                lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    secrets: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        secrets[key.strip()] = value.strip()
    return secrets


def write_secrets(secrets_dir: Path, secrets: Mapping[str, str]) -> Path:
    secrets_dir.mkdir(parents=True, exist_ok=True)
    path = secrets_dir / ".env"
    lines = [f"{key}={value}" for key, value in sorted(secrets.items())]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return path


def read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except OSError:
        return {}
    except tomllib.TOMLDecodeError as error:
        print(f"warning: ignoring malformed {path}: {error}", file=sys.stderr)
        return {}


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def collect_answers(previous: Mapping[str, Any]) -> dict[str, Any]:
    plugin = previous.get("plugin", {})
    voice_llm = plugin.get("voice_llm", {}) if isinstance(plugin, dict) else {}
    whisper = plugin.get("audio_processor_whisper", {}) if isinstance(plugin, dict) else {}
    zonos = plugin.get("audio_output_zonos", {}) if isinstance(plugin, dict) else {}
    answers: dict[str, Any] = {
        "plugin": {
            "voice_llm": {
                "endpoint": _ask("LLM base URL", str(voice_llm.get("endpoint", ""))),
                "model": _ask("LLM model name", str(voice_llm.get("model", ""))),
            },
            "audio_processor_whisper": {
                "endpoint": _ask("Whisper ASR URL", str(whisper.get("endpoint", ""))),
            },
            "audio_output_zonos": {
                "endpoint": _ask("Zonos TTS URL", str(zonos.get("endpoint", ""))),
            },
        }
    }
    camb_key = _ask("Camb AI API key (blank to skip)", "")
    answers["plugin"]["audio_output_camb"] = {"api_key": "env:KATETO_CAMB_API_KEY" if camb_key else ""}
    answers["secrets"] = {"KATETO_CAMB_API_KEY": camb_key}
    return answers


def run_setup(config_dir: Path | None = None, defaults_dir: Path | None = None) -> int:
    config_dir = config_dir or resolve_config_dir()
    defaults_dir = defaults_dir or default_config_dir()
    defaults_raw = read_toml(defaults_dir / "config.toml")
    config_file = config_dir / "config.toml"
    current_raw = read_toml(config_file) if config_file.is_file() else {}
    answers = collect_answers(current_raw or defaults_raw)
    secrets = dict(read_env_file(config_dir / "secrets" / ".env"))
    new_keys = {key: value for key, value in answers.pop("secrets", {}).items() if value}
    if new_keys:
        secrets.update(new_keys)
        write_secrets(config_dir / "secrets", secrets)
    merged = deep_merge(defaults_raw, current_raw)
    merged = deep_merge(merged, answers)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(dumps_toml(merged))
    print(f"Wrote {config_file}")
    _print_next_steps(merged)
    return 0


def _print_next_steps(merged: Mapping[str, Any]) -> None:
    plugins = merged.get("plugin", {})
    if isinstance(plugins, dict):
        voice_llm = plugins.get("voice_llm", {})
        if isinstance(voice_llm, dict) and voice_llm.get("endpoint") and "11434" in str(voice_llm.get("endpoint", "")):
            print("Next: `kateto doctor` to verify models, or `kateto run` to start.")
    else:
        print("Next: `kateto doctor` to verify, or `kateto run` to start.")