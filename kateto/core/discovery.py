from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from weakref import WeakKeyDictionary
from typing import Any

from kateto.core.config import LoadedConfig, PluginSettings
from kateto.core.plugin import Plugin


class LiveAssemblyConfigurationError(Exception):
    def __init__(self, *, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason

    def __str__(self) -> str:
        return f"live assembly requires {self.field}: {self.reason}"


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    config: LoadedConfig
    shared: dict[str, Any]

    def plugin_settings(self, name: str) -> PluginSettings:
        return required_plugin_settings(self.config, name)

    def get_shared(self, key: str, factory: Callable[[], Any] | None = None) -> Any:
        if key not in self.shared and factory is not None:
            self.shared[key] = factory()
        return self.shared.get(key)


@dataclass(frozen=True, slots=True)
class PluginRegistry:
    plugins: frozenset[Plugin]


_DISCOVERY_CONTEXTS: WeakKeyDictionary[Plugin, DiscoveryContext] = WeakKeyDictionary()


def required_plugin_settings(config: LoadedConfig, name: str) -> PluginSettings:
    settings = config.settings.plugin.get(name)
    if settings is None:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}", reason="must be configured")
    if not settings.enabled:
        raise LiveAssemblyConfigurationError(field=f"plugin.{name}.enabled", reason="must be true")
    return settings


def discover_plugins(context: DiscoveryContext) -> PluginRegistry:
    discovered: list[Plugin] = []
    discovered.extend(_scan_plugins(context))
    discovered.extend(_scan_voices(context))
    plugin_names = {plugin.name for plugin in discovered}
    if len(plugin_names) != len(discovered):
        raise LiveAssemblyConfigurationError(field="plugin", reason="plugin names must be unique")
    plugins = frozenset(discovered)
    if not any(plugin.name in set(context.config.settings.voice) for plugin in plugins):
        raise LiveAssemblyConfigurationError(field="voice", reason="at least one P0 voice must be enabled")
    for plugin in plugins:
        _DISCOVERY_CONTEXTS[plugin] = context
    return PluginRegistry(plugins=plugins)


def discovery_context_for(plugins: tuple[Plugin, ...]) -> DiscoveryContext | None:
    for plugin in plugins:
        context = _DISCOVERY_CONTEXTS.get(plugin)
        if context is not None:
            return context
    return None


def _scan_plugins(ctx: DiscoveryContext) -> list[Plugin]:
    plugins: list[Plugin] = []
    base = Path(__file__).resolve().parent.parent / "plugins"
    if not base.is_dir():
        return plugins
    for entry in sorted(base.iterdir()):
        init = entry / "__init__.py"
        if not init.exists():
            continue
        try:
            mod = import_module(f"kateto.plugins.{entry.name}")
        except (ModuleNotFoundError, ImportError):
            continue
        factory = getattr(mod, "create_plugins", None)
        if factory is None:
            continue
        try:
            for plugin in factory(ctx):
                plugins.append(plugin)
        except LiveAssemblyConfigurationError:
            continue
    return plugins


def _scan_voices(ctx: DiscoveryContext) -> list[Plugin]:
    voices: list[Plugin] = []
    base = Path(__file__).resolve().parent.parent / "voices"
    if not base.is_dir():
        return voices
    for entry in sorted(base.iterdir()):
        if entry.suffix != ".py" or entry.name.startswith("_"):
            continue
        mod = import_module(f"kateto.voices.{entry.stem}")
        factory = getattr(mod, "create_voice", None)
        if factory is None:
            continue
        settings = ctx.config.settings.voice.get(entry.stem)
        if settings is not None and settings.enabled:
            voices.append(factory(ctx, settings))
    return voices
