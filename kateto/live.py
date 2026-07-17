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
    "EventRuntime",
    "build_event_runtime",
]


class EventRuntime:
    def __init__(
        self,
        *,
        manager: PluginManager,
        plugins: tuple[Plugin, ...],
    ) -> None:
        self.manager: PluginManager = manager
        self._plugins: frozenset[Plugin] = frozenset(plugins)
        self._started: bool = False

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        return tuple(self._plugins)

    async def start(self) -> None:
        if self._started:
            return
        try:
            for plugin in self._plugins:
                await self.manager.enable_plugin(plugin)
        except BaseException:  # noqa: BROAD_EXCEPT_OK
            await self.stop()
            raise
        self._started = True

    async def stop(self) -> None:
        await self.manager.close()
        self._started = False


def build_event_runtime(
    config: LoadedConfig,
    *,
    shared: dict[str, Any] | None = None,
) -> EventRuntime:
    registry = discover_plugins(
        DiscoveryContext(config=config, shared=shared or {}),
    )
    return EventRuntime(
        manager=PluginManager(),
        plugins=tuple(registry.plugins),
    )
