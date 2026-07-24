from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, final

from kateto.core.config import LoadedConfig
from kateto.core.event import VoiceEnableData, VoiceEnabledData
from kateto.core.discovery import (
    DiscoveryContext,
    LiveAssemblyConfigurationError,
    discover_plugins,
)
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog
from kateto.core.workflow_engine import WorkflowEngine
from kateto.live import build_event_runtime
from kateto.plugins.system.external_mcp import ExternalMcpManager
from kateto.plugins.system.mcp_server import McpEventServer, McpServerOptions
from kateto.plugins.system.voice_manager import VoiceManager
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.connector.calendar import CalendarFailure, build_google_calendar_connector


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    shared: dict[str, Any] | None = None
    calendar_factory: Callable[[Path], Plugin] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    plugins: tuple[Plugin, ...]
    mcp_servers: tuple[McpEventServer, ...]
    workflow_voices: tuple[str, ...]
    external_mcp: ExternalMcpManager | None = None
    http_server: HttpServer | None = None


@final
class RuntimeOwner:
    def __init__(
        self,
        *,
        manager: PluginManager,
        plugins: tuple[Plugin, ...],
        components: RuntimeComponents,
        config: LoadedConfig | None = None,
    ) -> None:
        self._manager = manager
        self._plugins = plugins
        self._components = components
        self._config = config
        self._started = False

    @property
    def manager(self) -> PluginManager:
        return self._manager

    @property
    def runtime_plugins(self) -> tuple[Plugin, ...]:
        plugins = {plugin.name: plugin for plugin in self._plugins}
        plugins.update({plugin.name: plugin for plugin in self._manager.get_plugins()})
        return tuple(plugins.values())

    @property
    def workflow_voices(self) -> tuple[str, ...]:
        return self._components.workflow_voices

    @property
    def config(self) -> LoadedConfig | None:
        return self._config

    def voice_enabled(self, name: str) -> bool:
        normalized = name.casefold()
        for plugin in self._manager.get_plugins():
            if plugin.name.casefold() == normalized:
                return plugin.enabled
            profile = getattr(plugin, "profile", None)
            display_name = getattr(profile, "display_name", None)
            if isinstance(display_name, str) and display_name.casefold() == normalized:
                return plugin.enabled
        if self._config is None:
            return True
        voice_cfg = self._config.settings.voice.get(name)
        return voice_cfg.enabled if voice_cfg else True

    @property
    def mcp_servers(self) -> tuple[McpEventServer, ...]:
        return self._components.mcp_servers

    @property
    def external_mcp(self) -> ExternalMcpManager | None:
        return self._components.external_mcp

    @property
    def http_server(self) -> HttpServer | None:
        return self._components.http_server

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
            for plugin in self._plugins:
                await self._manager.enable_plugin(plugin)
            voice_mgr = VoiceManager(
                self._config.settings.plugin.get("voice_manager") if self._config else None,
                on_voice_enable=self.on_voice_enable,
            )
            await self._manager.enable_plugin(voice_mgr)
            # Start external MCP servers after plugins so voice enable runs first,
            # but before internal event-server refresh so external tools are visible.
            external_mcp = self.external_mcp
            if external_mcp is not None:
                await external_mcp.start_all()
                await self._sync_external_tools()
            for server in self.mcp_servers:
                server.refresh_tools()
            http_server = self.http_server
            if http_server is not None:
                await http_server.start()
        except BaseException:  # noqa: BROAD_EXCEPT_OK
            await self.stop()
            raise
        self._started = True

    async def _sync_external_tools(self) -> None:
        """Push external MCP tools into every active voice agent's tool list."""
        from kateto.voices.base import VoiceAgent

        external_mcp = self.external_mcp
        if external_mcp is None:
            return
        for plugin in self._manager.get_plugins():
            if not isinstance(plugin, VoiceAgent) or not plugin.enabled:
                continue
            server_names = external_mcp.get_servers_for_voice(plugin.name)
            if not server_names:
                continue
            tools = await external_mcp.get_tools_for(server_names)
            if tools:
                plugin.add_extra_tools(tools)

    async def stop(self) -> None:
        try:
            try:
                http_server = self.http_server
                if http_server is not None:
                    await http_server.stop()
            finally:
                try:
                    external_mcp = self.external_mcp
                    if external_mcp is not None:
                        await external_mcp.stop_all()
                finally:
                    try:
                        await self._close_mcp_servers()
                    finally:
                        await self._manager.close()
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

    async def on_voice_enable(self, data: VoiceEnableData) -> None:
        voice_name = data.voice_name
        config = self._config
        if config is None:
            msg = "runtime config not available for voice enable"
            raise RuntimeError(msg)
        configured_name = next(
            (name for name in config.settings.voice if name.casefold() == voice_name.casefold()),
            None,
        )
        voice_settings = config.settings.voice.get(configured_name) if configured_name else None
        if voice_settings is None:
            msg = f"voice not configured: {voice_name}"
            raise ValueError(msg)
        for plugin in self._manager.get_plugins():
            if plugin.name.casefold() == voice_name.casefold():
                if plugin.enabled:
                    await self._manager.emit(
                        "voice_enabled",
                        VoiceEnabledData(voice_name=plugin.name),
                        source="voice_manager",
                    )
                    return
                await self._manager.enable_plugin(plugin)
                await self._manager.emit(
                    "voice_enabled",
                    VoiceEnabledData(voice_name=plugin.name),
                    source="voice_manager",
                )
                return
        from kateto.voices.factory import create_voice

        ctx = DiscoveryContext(config=config, shared={}, external_mcp=self._components.external_mcp)
        voice = create_voice(ctx, voice_settings, voice_name=configured_name or voice_name)
        await self._manager.enable_plugin(voice)
        await self._manager.emit(
            "voice_enabled",
            VoiceEnabledData(voice_name=voice.name),
            source="voice_manager",
        )


def build_runtime_owner(
    config: LoadedConfig,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> RuntimeOwner:
    resolved_dependencies = RuntimeDependencies() if dependencies is None else dependencies

    # --- external MCP (created early so voice factory can reference it) ---
    external_mcp = ExternalMcpManager()
    for voice_name, voice in config.settings.voice.items():
        if not voice.enabled:
            continue
        for server_name in voice.mcp_servers:
            if server_name == "system":
                continue
            server_settings = config.settings.mcp_servers.get(server_name)
            if server_settings is not None:
                external_mcp.configure(voice_name, server_name, server_settings)

    shared = resolved_dependencies.shared
    if shared is None:
        shared = {}

    manager, discovered = build_event_runtime(
        config,
        shared=shared,
        external_mcp=external_mcp,
    )
    runtime_plugins = (
        *discovered,
        WorkflowEngine(config_dir=config.paths.config_dir),
        *_configured_calendar(config, resolved_dependencies),
    )
    mcp_servers = _authorized_mcp_servers(manager, config)
    http_settings = config.settings.plugin.get("http_server")
    http_server = HttpServer(manager) if http_settings is not None and http_settings.enabled else None
    return RuntimeOwner(
        manager=manager,
        plugins=runtime_plugins,
        config=config,
        components=RuntimeComponents(
            plugins=(),
            mcp_servers=mcp_servers,
            workflow_voices=tuple(config.settings.voice.keys()),
            external_mcp=external_mcp if external_mcp._clients else None,
            http_server=http_server,
        ),
    )


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
            config_dir=config.paths.config_dir,
        )
        for voice_name, voice in config.settings.voice.items()
        if voice.enabled
        for server_name in voice.mcp_servers
        if server_name == "system"  # only internal event servers
    )
