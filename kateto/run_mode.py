from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, final

from kateto.core.config import LoadedConfig
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog
from kateto.core.workflow_engine import WorkflowEngine
from kateto.live import (
    LiveAssemblyConfigurationError,
    LiveConversation,
    LiveDependencies,
    ManagedProvider,
    build_live_conversation,
)
from kateto.plugins.system.mcp_server import McpEventServer, McpServerOptions
from kateto.plugins.connector.calendar import CalendarFailure, build_google_calendar_connector


class CalendarConnectorFactory(Protocol):
    def __call__(self, config_dir: Path) -> Plugin: ...


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    live: LiveDependencies | None = None
    calendar_factory: CalendarConnectorFactory | None = None


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    plugins: tuple[Plugin, ...]
    mcp_servers: tuple[McpEventServer, ...]
    hot_reload_controller: HotReloadController | None


@final
class RuntimeOwner:
    """Own the configured non-audio runtime components around a live conversation."""

    def __init__(
        self,
        *,
        live: LiveConversation,
        components: RuntimeComponents,
    ) -> None:
        self._live = live
        self._components = components
        self._started = False

    @property
    def manager(self) -> PluginManager:
        return self._live.manager

    @property
    def providers(self) -> tuple[ManagedProvider, ...]:
        return self._live.providers

    @property
    def runtime_plugins(self) -> tuple[Plugin, ...]:
        return self._components.plugins

    @property
    def mcp_servers(self) -> tuple[McpEventServer, ...]:
        return self._components.mcp_servers

    @property
    def hot_reload_controller(self) -> HotReloadController | None:
        return self._components.hot_reload_controller

    @property
    def workflow_engine(self) -> WorkflowEngine:
        return next(
            plugin
            for plugin in self.runtime_plugins
            if isinstance(plugin, WorkflowEngine)
        )

    @property
    def workflow_catalog(self) -> WorkflowCatalog:
        return self.workflow_engine.catalog

    @property
    def is_started(self) -> bool:
        return self._started

    async def start(self) -> None:
        if self._started:
            return
        try:
            await self._live.start()
            for plugin in self.runtime_plugins:
                await self.manager.enable_plugin(plugin)
            for server in self.mcp_servers:
                server.refresh_tools()
            controller = self.hot_reload_controller
            if controller is not None:
                controller.loop = asyncio.get_running_loop()
                await controller.start()
        except BaseException:  # noqa: BROAD_EXCEPT_OK
            await self.stop()
            raise
        self._started = True

    async def stop(self) -> None:
        try:
            try:
                controller = self.hot_reload_controller
                if controller is not None:
                    await controller.close()
            finally:
                try:
                    await self._close_mcp_servers()
                finally:
                    await self._live.stop()
        finally:
            self._started = False

    async def _close_mcp_servers(self) -> None:
        results = await asyncio.gather(
            *(server.close() for server in reversed(self.mcp_servers)),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result


def build_runtime_owner(
    config: LoadedConfig,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> RuntimeOwner:
    resolved_dependencies = RuntimeDependencies() if dependencies is None else dependencies
    live = build_live_conversation(config, dependencies=resolved_dependencies.live)
    runtime_plugins = (
        WorkflowEngine(config_dir=config.paths.config_dir),
        *_configured_calendar(config, resolved_dependencies),
    )
    mcp_servers = _authorized_mcp_servers(live.manager, config)
    controller = (
        HotReloadController(manager=live.manager, watched_root=config.paths.config_dir)
        if config.settings.kateto.hot_reload
        else None
    )
    return RuntimeOwner(
        live=live,
        components=RuntimeComponents(
            plugins=runtime_plugins,
            mcp_servers=mcp_servers,
            hot_reload_controller=controller,
        ),
    )


async def run_live(
    config: LoadedConfig,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> None:
    owner = build_runtime_owner(config, dependencies=dependencies)
    await owner.start()
    try:
        _ = await asyncio.Event().wait()
    finally:
        await owner.stop()


def _configured_calendar(
    config: LoadedConfig,
    dependencies: RuntimeDependencies,
) -> tuple[Plugin, ...]:
    settings = config.settings.plugin.get("connector_calendar")
    if settings is None or not settings.enabled:
        return ()
    factory = dependencies.calendar_factory
    if factory is None:
        try:
            connector = build_google_calendar_connector(
                config.paths.config_dir,
                endpoint=settings.endpoint,
            )
        except CalendarFailure as error:
            raise LiveAssemblyConfigurationError(
                field="plugin.connector_calendar",
                reason=f"Google Calendar provider is unavailable: {error}",
            ) from error
    else:
        connector = factory(config.paths.config_dir)
    if connector.name != "connector_calendar":
        raise LiveAssemblyConfigurationError(
            field="plugin.connector_calendar",
            reason="factory must return the connector_calendar plugin",
        )
    return (connector,)


def _authorized_mcp_servers(
    manager: PluginManager,
    config: LoadedConfig,
) -> tuple[McpEventServer, ...]:
    return tuple(
        McpEventServer(
            manager,
            config.settings,
            McpServerOptions(server_name=server_name, voice_name=voice_name),
        )
        for voice_name, voice in config.settings.voice.items()
        if voice.enabled
        for server_name in voice.mcp_servers
    )


RunOwner = RuntimeOwner
LiveRuntime = RuntimeOwner
