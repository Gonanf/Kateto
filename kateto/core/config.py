from __future__ import annotations

import os
import shutil
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath
from typing import Final, Self
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


SAFE_CLI_COMMANDS: Final[frozenset[str]] = frozenset({"cat", "date", "echo", "git", "ls", "pwd"})
_ASSET_FIELDS: Final[tuple[str, ...]] = (
    "journal",
    "memories",
    "reference_audio",
    "reference_clip",
    "soul",
)


@dataclass(frozen=True, slots=True)
class ConfigPathError(Exception):
    variable: str

    def __str__(self) -> str:
        return f"missing required config path environment variable: {self.variable}"


@dataclass(frozen=True, slots=True)
class ConfigBootstrapError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"unable to bootstrap config at {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ConfigReadError(Exception):
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"unable to read config at {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ConfigTomlError(Exception):
    path: Path

    def __str__(self) -> str:
        return f"malformed TOML in {self.path}"


@dataclass(frozen=True, slots=True)
class ConfigValidationError(Exception):
    path: Path
    issue: str

    def __str__(self) -> str:
        return f"invalid config in {self.path}: {self.issue}"


@dataclass(frozen=True, slots=True)
class CliCommandRejectedError(Exception):
    executable: str

    def __str__(self) -> str:
        return f"cli command rejected: {self.executable}"


@dataclass(frozen=True, slots=True)
class ConfigPaths:
    config_dir: Path
    config_file: Path
    dotenv_file: Path
    secrets_dir: Path


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class KatetoSettings(_ConfigModel):
    debug: bool = False
    hot_reload: bool = False
    language: str = "en"
    name: str = "Kateto"


class PluginSettings(_ConfigModel):
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


class VoiceSettings(_ConfigModel):
    enabled: bool = True
    skills: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    soul: str | None = None
    journal: str | None = None
    memories: str | None = None
    reference_audio: str | None = None
    reference_clip: str | None = None

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
    allowlist: list[str] = Field(min_length=1)

    @field_validator("allowlist")
    @classmethod
    def validate_allowlist(cls, value: list[str]) -> list[str]:
        for executable in value:
            if executable not in SAFE_CLI_COMMANDS:
                raise ValueError(f"contains rejected command {executable!r}")
        return value


class KatetoConfig(_ConfigModel):
    kateto: KatetoSettings
    plugin: dict[str, PluginSettings] = Field(default_factory=dict)
    voice: dict[str, VoiceSettings] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerSettings] = Field(default_factory=dict)
    cli: CliSettings

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
            raise ConfigPathError(variable="APPDATA")
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
        raise ConfigBootstrapError(path=source_dir, reason="default config directory is missing")
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        _copy_missing_defaults(source_dir=source_dir, target_dir=target_dir)
        paths.secrets_dir.mkdir(exist_ok=True)
    except OSError as error:
        raise ConfigBootstrapError(path=target_dir, reason=str(error)) from error
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


def load_config(*, config_dir: Path | None = None, defaults_dir: Path | None = None) -> LoadedConfig:
    paths = bootstrap_config(config_dir=config_dir, defaults_dir=defaults_dir)
    try:
        raw_config = tomllib.loads(paths.config_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigTomlError(path=paths.config_file) from error
    except UnicodeDecodeError as error:
        raise ConfigReadError(path=paths.config_file, reason="config must use UTF-8") from error
    except OSError as error:
        raise ConfigReadError(path=paths.config_file, reason=str(error)) from error
    try:
        settings = KatetoConfig.model_validate(raw_config)
    except ValidationError as error:
        raise ConfigValidationError(
            path=paths.config_file,
            issue=_format_validation_error(error),
        ) from error
    _validate_assets(config_dir=paths.config_dir, config_file=paths.config_file, settings=settings)
    _load_dotenv(paths)
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
                raise ConfigValidationError(path=config_file, issue=f"{setting_path}: asset escapes config directory")
            if not resolved_asset.is_file():
                raise ConfigValidationError(path=config_file, issue=f"{setting_path}: asset does not exist")


def _load_dotenv(paths: ConfigPaths) -> None:
    for dotenv_path in (paths.dotenv_file, paths.secrets_dir / ".env"):
        if dotenv_path.is_file():
            load_dotenv(dotenv_path=dotenv_path, override=False)


def validate_cli_command(command: Sequence[str], *, settings: CliSettings) -> tuple[str, ...]:
    if not command:
        raise CliCommandRejectedError(executable="<empty>")
    executable = command[0]
    if Path(executable).name != executable or executable not in settings.allowlist:
        raise CliCommandRejectedError(executable=executable)
    return tuple(command)
