from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, final

from kateto.core.config import LoadedConfig
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog
from kateto.core.workflow_engine import WorkflowEngine
from kateto.live import (
    EventRuntime,
    EventRuntimeConfigurationError,
    build_event_runtime,
)
from kateto.plugins.system.mcp_server import McpEventServer, McpServerOptions
from kateto.plugins.connector.calendar import CalendarFailure, build_google_calendar_connector
from kateto.plugins.system.tui_runtime import TuiConfigurationRuntime, TuiPluginConfiguration


class CalendarConnectorFactory(Protocol):
    def __call__(self, config_dir: Path) -> Plugin: ...


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    shared: dict[str, Any] | None = None
    calendar_factory: CalendarConnectorFactory | None = None


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    plugins: tuple[Plugin, ...]
    mcp_servers: tuple[McpEventServer, ...]
    hot_reload_controller: HotReloadController | None
    workflow_voices: tuple[str, ...]


@final
class RuntimeOwner(TuiConfigurationRuntime):
    def __init__(
        self,
        *,
        event_runtime: EventRuntime,
        components: RuntimeComponents,
        plugin_configurations: tuple[TuiPluginConfiguration, ...] = (),
    ) -> None:
        self._event_runtime = event_runtime
        self._components = components
        self._started = False
        self._plugin_configurations = {item.plugin: item for item in plugin_configurations}

    @property
    def manager(self) -> PluginManager:
        return self._event_runtime.manager

    @property
    def runtime_plugins(self) -> tuple[Plugin, ...]:
        return (*self._event_runtime.plugins, *self._components.plugins)

    @property
    def workflow_voices(self) -> tuple[str, ...]:
        return self._components.workflow_voices

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

    @property
    def plugin_configurations(self) -> tuple[TuiPluginConfiguration, ...]:
        return tuple(self._plugin_configurations.values())

    def plugin_configuration(self, name: str) -> TuiPluginConfiguration | None:
        return self._plugin_configurations.get(name)

    async def configure_plugin(self, name: str, configuration: TuiPluginConfiguration) -> None:
        if configuration.plugin != name:
            raise ValueError("plugin configuration name must match its key")
        if name not in self._plugin_configurations:
            raise ValueError(f"plugin configuration is not editable: {name}")
        self._plugin_configurations[name] = configuration

    async def start(self) -> None:
        if self._started:
            return
        try:
            await self._event_runtime.start()
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
                    await self._event_runtime.stop()
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
    event_runtime = build_event_runtime(
        config,
        shared=resolved_dependencies.shared,
    )
    runtime_plugins = (
        WorkflowEngine(config_dir=config.paths.config_dir),
        *_configured_calendar(config, resolved_dependencies),
    )
    mcp_servers = _authorized_mcp_servers(event_runtime.manager, config)
    controller = (
        HotReloadController(
            manager=event_runtime.manager,
            watched_root=config.paths.config_dir,
            source_roots=(
                Path(__file__).resolve().parent / "plugins",
                Path(__file__).resolve().parent / "voices",
            ),
        )
        if config.settings.kateto.hot_reload
        else None
    )
    return RuntimeOwner(
        event_runtime=event_runtime,
        components=RuntimeComponents(
            plugins=runtime_plugins,
            mcp_servers=mcp_servers,
            hot_reload_controller=controller,
            workflow_voices=tuple(
                name
                for name, settings in config.settings.voice.items()
                if settings.enabled
            ),
        ),
        plugin_configurations=_tui_plugin_configurations(config),
    )


def _tui_plugin_configurations(config: LoadedConfig) -> tuple[TuiPluginConfiguration, ...]:
    configurations: list[TuiPluginConfiguration] = []
    for name, setting in config.settings.plugin.items():
        if name.startswith("audio_input_"):
            configurations.append(TuiPluginConfiguration(plugin=name, microphone=setting.device))
        elif name == "audio_output_player":
            configurations.append(TuiPluginConfiguration(plugin=name, speaker=setting.device))
    return tuple(configurations)


async def run_event_runtime(
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
            raise EventRuntimeConfigurationError(
                field="plugin.connector_calendar",
                reason=f"Google Calendar provider is unavailable: {error}",
            ) from error
    else:
        connector = factory(config.paths.config_dir)
    if connector.name != "connector_calendar":
        raise EventRuntimeConfigurationError(
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
