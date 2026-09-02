from __future__ import annotations

import os
import shutil
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Final, Self
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from kateto.core.event import EventModel

from kateto.core.exceptions import ConfigError


SAFE_CLI_COMMANDS: Final[frozenset[str]] = frozenset({"cat", "date", "echo", "git", "ls", "pwd"})
_ASSET_FIELDS: Final[tuple[str, ...]] = (
    "journal",
    "memories",
    "reference_audio",
    "reference_clip",
    "soul",
)


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    config_dir: Path
    config_file: Path
    dotenv_file: Path
    secrets_dir: Path


class _ConfigModel(EventModel):
    ...


class _ExtensibleConfigModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    def __getattr__(self, name: str) -> Any:
        if self.model_extra and name in self.model_extra:
            return self.model_extra[name]
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


class PluginConfigRegistry:
    """Registry allowing plugins to declare custom parameters for themselves or for voices."""
    _plugin_params: dict[str, dict[str, Any]] = {}
    _voice_params: dict[str, Any] = {}

    @classmethod
    def register_plugin_param(cls, plugin_name: str, param_name: str, default: Any = None) -> None:
        if plugin_name not in cls._plugin_params:
            cls._plugin_params[plugin_name] = {}
        cls._plugin_params[plugin_name][param_name] = default

    @classmethod
    def register_voice_param(cls, param_name: str, default: Any = None) -> None:
        cls._voice_params[param_name] = default

    @classmethod
    def get_plugin_defaults(cls, plugin_name: str) -> dict[str, Any]:
        return dict(cls._plugin_params.get(plugin_name, {}))

    @classmethod
    def get_voice_defaults(cls) -> dict[str, Any]:
        return dict(cls._voice_params)


def register_plugin_param(plugin_name: str, param_name: str, default: Any = None) -> None:
    PluginConfigRegistry.register_plugin_param(plugin_name, param_name, default)


def register_voice_param(param_name: str, default: Any = None) -> None:
    PluginConfigRegistry.register_voice_param(param_name, default)


class KatetoSettings(_ConfigModel):
    debug: bool = False
    hot_reload: bool = False
    language: str = "en"
    name: str = "Kateto"
    log_level: str = "INFO"
    default_voice_dept: str = "fun"


class PluginSettings(_ExtensibleConfigModel):
    enabled: bool = True
    endpoint: str | None = None
    model: str | None = None
    model_endpoint: str | None = None
    api_key: str | None = None
    silence_timeout: float | None = Field(default=None, gt=0)
    sample_rate: int | None = Field(default=None, gt=0)
    device: str | None = None
    vad_model: str | None = None
    vad_threshold: float | None = Field(default=None, ge=0, le=1)
    interrupt_on_vad: bool | None = None
    interrupt_llm: bool | None = None
    interrupt_tts: bool | None = None
    context_window: int | None = Field(default=None, gt=0)
    stream: bool = True
    callback_queue_capacity: int | None = Field(default=None, gt=0)
    default_voice_id: int | None = None
    default_language: str | None = None
    language: str | None = None
    voice_probabilities: dict[str, float] | None = None
    conversation_id: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, lt=65536)
    dept: str | None = None
    depts: list[str] | None = None
    # Local (subprocess) backend: when set, `model` is a file path, not a server name.
    command: str | None = None
    args: list[str] | None = None
    backend: str | None = None

    @field_validator("endpoint", "model_endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an http(s) endpoint")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not include credentials")
        return value


class VoiceSettings(_ExtensibleConfigModel):
    enabled: bool = True
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    dept: str | None = None
    depts: list[str] | None = None
    soul: str | None = None
    journal: str | None = None
    memories: str | None = None
    reference_audio: str | None = None
    reference_clip: str | None = None
    stream: bool = True
    tts_provider: str = "zonos"
    camb_voice_id: int | None = None
    camb_language: str | None = None
    edge_tts_voice: str | None = None
    max_tokens: int | None = None
    retries: int | None = None
    timeout: float | None = None

    @model_validator(mode="after")
    def validate_dept_fields(self) -> Self:
        if self.dept is not None and self.depts is not None:
            raise ValueError("dept and depts are mutually exclusive")
        return self

    @field_validator("dept")
    @classmethod
    def casefold_dept(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None

    @field_validator("depts")
    @classmethod
    def casefold_depts(cls, value: list[str] | None) -> list[str] | None:
        return [item.casefold() for item in value] if value is not None else None

    @field_validator(*_ASSET_FIELDS)
    @classmethod
    def validate_asset_syntax(cls, value: str | None) -> str | None:
        if value is None:
            return None
        posix_path = PurePath(value)
        windows_path = PureWindowsPath(value)
        if (
            not value
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or ".." in posix_path.parts
            or ".." in windows_path.parts
        ):
            raise ValueError("must be a relative asset path inside the config directory")
        return value


class McpServerSettings(_ConfigModel):
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)


class CliSettings(_ConfigModel):
    allowlist: list[str] | None = Field(
        default_factory=lambda: sorted(SAFE_CLI_COMMANDS),
        description=(
            "Executables the CLI connector may run. Defaults to SAFE_CLI_COMMANDS. "
            "Set to [] to disable the allowlist entirely (unrestricted execution — security risk)."
        ),
    )
    cli_restricted: bool = Field(
        default=True,
        description=(
            "When False, skip per-argument path/shell validation. The command "
            "allowlist (if any) still applies. Disabling is a security risk."
        ),
    )

    @field_validator("allowlist")
    @classmethod
    def validate_allowlist(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for executable in value:
            if executable not in SAFE_CLI_COMMANDS:
                raise ValueError(f"contains rejected command {executable!r}")
        return value


class CompilerTargetSettings(_ConfigModel):
    backend: str = "vulkan"
    cmake_args: list[str] = Field(default_factory=list)


class CompilerSettings(_ConfigModel):
    whisper: CompilerTargetSettings = Field(default_factory=CompilerTargetSettings)
    llama: CompilerTargetSettings = Field(default_factory=CompilerTargetSettings)


class KatetoConfig(_ConfigModel):
    kateto: KatetoSettings
    plugin: dict[str, PluginSettings] = Field(default_factory=dict)
    voice: dict[str, VoiceSettings] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerSettings] = Field(default_factory=dict)
    cli: CliSettings
    compiler: CompilerSettings = Field(default_factory=CompilerSettings)

    @model_validator(mode="after")
    def validate_voice_mcp_servers(self) -> Self:
        for voice_name, voice_settings in self.voice.items():
            for server_name in voice_settings.mcp_servers:
                if server_name not in self.mcp_servers:
                    msg = f"voice.{voice_name}.mcp_servers references undeclared server {server_name!r}"
                    raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    paths: ConfigPaths
    settings: KatetoConfig


def resolve_config_dir(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home_dir: Path | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    current_platform = sys.platform if platform_name is None else platform_name
    if current_platform == "win32":
        appdata = environment.get("APPDATA")
        if appdata is None or not appdata.strip():
            raise ConfigError("missing required config path environment variable: APPDATA")
        return Path(appdata) / "kateto"
    xdg_config_home = environment.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "kateto"
    base_home = Path.home() if home_dir is None else home_dir
    return base_home / ".config" / "kateto"


def default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "defaults"


def bootstrap_config(
    *,
    config_dir: Path | None = None,
    defaults_dir: Path | None = None,
) -> ConfigPaths:
    target_dir = resolve_config_dir() if config_dir is None else config_dir
    source_dir = default_config_dir() if defaults_dir is None else defaults_dir
    paths = ConfigPaths(
        config_dir=target_dir,
        config_file=target_dir / "config.toml",
        dotenv_file=target_dir / ".env",
        secrets_dir=target_dir / "secrets",
    )
    if paths.config_file.exists():
        return paths
    if not source_dir.is_dir():
        raise ConfigError(f"unable to bootstrap config at {source_dir}: default config directory is missing")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        _copy_missing_defaults(source_dir=source_dir, target_dir=target_dir)
        paths.secrets_dir.mkdir(exist_ok=True)
    except OSError as error:
        raise ConfigError(f"unable to bootstrap config at {target_dir}: {error}") from error
    return paths


def _copy_missing_defaults(*, source_dir: Path, target_dir: Path) -> None:
    for source_path in source_dir.rglob("*"):
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file() and not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def _load_voice_folder_configs(config_dir: Path, raw_config: dict[str, Any]) -> None:
    voices_section = raw_config.setdefault("voice", {})
    voices_dir = config_dir / "voices"
    if not voices_dir.is_dir():
        return
    for voice_entry in sorted(voices_dir.iterdir()):
        if not voice_entry.is_dir():
            continue
        vname = voice_entry.name.casefold()
        cfg_file = None
        for candidate in ("config.toml", "voice.toml"):
            candidate_path = voice_entry / candidate
            if candidate_path.is_file():
                cfg_file = candidate_path
                break
        if cfg_file is not None:
            try:
                vdata = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
                if "voice" in vdata and isinstance(vdata["voice"], dict):
                    if vname in vdata["voice"] and isinstance(vdata["voice"][vname], dict):
                        vsettings = vdata["voice"][vname]
                    else:
                        vsettings = vdata["voice"]
                else:
                    vsettings = vdata

                existing = voices_section.get(vname, {})
                voices_section[vname] = {**existing, **vsettings}
            except Exception as err:
                raise ConfigError(f"unable to read voice config at {cfg_file}: {err}") from err
        elif vname not in voices_section and any((voice_entry / marker).exists() for marker in ("SOUL.md", "soul.md", "workflows")):
            voices_section[vname] = {"enabled": True}

    voice_defaults = PluginConfigRegistry.get_voice_defaults()
    for vname, vdata in voices_section.items():
        if isinstance(vdata, dict):
            for k, def_val in voice_defaults.items():
                if k not in vdata and def_val is not None:
                    vdata[k] = def_val


def load_config(*, config_dir: Path | None = None, defaults_dir: Path | None = None) -> LoadedConfig:
    paths = bootstrap_config(config_dir=config_dir, defaults_dir=defaults_dir)
    try:
        raw_config = tomllib.loads(paths.config_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"malformed TOML in {paths.config_file}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(f"unable to read config at {paths.config_file}: config must use UTF-8") from error
    except OSError as error:
        raise ConfigError(f"unable to read config at {paths.config_file}: {error}") from error

    _load_voice_folder_configs(paths.config_dir, raw_config)
    _load_dotenv(paths)
    _resolve_secret_references(raw_config)
    try:
        settings = KatetoConfig.model_validate(raw_config)
    except ValidationError as error:
        raise ConfigError(
            f"invalid config in {paths.config_file}: {_format_validation_error(error)}",
        ) from error
    _validate_assets(config_dir=paths.config_dir, config_file=paths.config_file, settings=settings)
    return LoadedConfig(paths=paths, settings=settings)


def _format_validation_error(error: ValidationError) -> str:
    issues = []
    for detail in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in detail["loc"])
        issues.append(f"{location}: {detail['msg']}")
    return "; ".join(issues)


def _validate_assets(*, config_dir: Path, config_file: Path, settings: KatetoConfig) -> None:
    resolved_root = config_dir.resolve()
    for voice_name, voice_settings in settings.voice.items():
        for field_name in _ASSET_FIELDS:
            asset_path = getattr(voice_settings, field_name)
            if asset_path is None:
                continue
            resolved_asset = (resolved_root / asset_path).resolve()
            setting_path = f"voice.{voice_name}.{field_name}"
            if not resolved_asset.is_relative_to(resolved_root):
                raise ConfigError(f"invalid config in {config_file}: {setting_path}: asset escapes config directory")
            if not resolved_asset.is_file():
                raise ConfigError(f"invalid config in {config_file}: {setting_path}: asset does not exist")


def _load_dotenv(paths: ConfigPaths) -> None:
    for dotenv_path in (paths.dotenv_file, paths.secrets_dir / ".env"):
        if dotenv_path.is_file():
            load_dotenv(dotenv_path=dotenv_path, override=False)


def resolve_secret(value: str | None) -> str | None:
    """Resolve an `env:NAME` reference to the environment value (or None).

    Kept for callers that read raw config (e.g. `kateto doctor`) so they
    mirror what load_config() injects into PluginSettings.api_key.
    """
    if value is None or not isinstance(value, str) or not value.startswith("env:"):
        return value
    name = value.removeprefix("env:")
    return os.environ.get(name) if name else None


def _resolve_secret_references(raw_config: Mapping[str, object]) -> None:
    plugin_sections = raw_config.get("plugin")
    if not isinstance(plugin_sections, dict):
        return
    for section in plugin_sections.values():
        if not isinstance(section, dict):
            continue
        api_key = section.get("api_key")
        if not isinstance(api_key, str) or not api_key.startswith("env:"):
            continue
        # Missing env var -> clear the key so the empty-key code path applies.
        section["api_key"] = resolve_secret(api_key)


def validate_cli_command(command: Sequence[str], *, settings: CliSettings) -> tuple[str, ...]:
    if not command:
        raise ConfigError("cli command rejected: <empty>")
    executable = command[0]
    allowlist = settings.allowlist
    # None/[] allowlist = unrestricted execution (explicit opt-in-out of the allowlist).
    if allowlist and (Path(executable).name != executable or executable not in allowlist):
        raise ConfigError(f"cli command rejected: {executable}")
    return tuple(command)
