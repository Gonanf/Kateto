from __future__ import annotations

from typing import Any

from kateto.core.config import LoadedConfig
from kateto.core.discovery import (
    DiscoveryContext,
    LiveAssemblyConfigurationError,
    discover_plugins,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


EventRuntimeConfigurationError = LiveAssemblyConfigurationError


__all__ = [
    "EventRuntimeConfigurationError",
    "build_event_runtime",
]


def build_event_runtime(
    config: LoadedConfig,
    *,
    shared: dict[str, Any] | None = None,
) -> tuple[PluginManager, tuple[Plugin, ...]]:
    registry = discover_plugins(
        DiscoveryContext(config=config, shared=shared or {}),
    )
    return PluginManager(), tuple(registry.plugins)
