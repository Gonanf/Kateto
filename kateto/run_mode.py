from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, final

from loguru import logger

from kateto.core.config import LoadedConfig
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog
from kateto.live import build_event_runtime

if TYPE_CHECKING:
    from kateto.plugins.system.external_mcp import ExternalMcpManager
    from kateto.plugins.system.http_server import HttpServer
    from kateto.plugins.system.mcp_server import McpEventServer


def _configure_logging(config: LoadedConfig) -> None:
    logger.remove()
    _ = logger.add(sys.stderr, level=config.settings.kateto.log_level.upper())


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    shared: dict[str, Any] | None = None


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
        shared: dict[str, Any] | None = None,
    ) -> None:
        self._manager = manager
        self._plugins = plugins
        self._components = components
        self._config = config
        self._shared = shared or {}
        self._started = False
        self._hot_reload: HotReloadController | None = None

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
    def workflow_engine(self) -> Plugin:
        return next(
            plugin
            for plugin in self.runtime_plugins
            if plugin.name == "workflow_engine"
        )

    @property
    def workflow_catalog(self) -> WorkflowCatalog:
        catalog = getattr(self.workflow_engine, "catalog", None)
        assert isinstance(catalog, WorkflowCatalog)
        return catalog

    @property
    def is_started(self) -> bool:
        return self._started

    def _config_enabled(self, plugin: Plugin) -> bool:
        if self._config is None:
            return True
        plugin_settings = self._config.settings.plugin.get(plugin.name)
        if plugin_settings is not None:
            return plugin_settings.enabled
        voice_settings = self._config.settings.voice.get(plugin.name)
        if voice_settings is not None:
            return voice_settings.enabled
        return True

    async def start(self) -> None:
        if self._started:
            return
        try:
            for plugin in self._plugins:
                if self._config_enabled(plugin):
                    await self._manager.enable_plugin(plugin)
                else:
                    self._manager.register_plugin(plugin)
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
                from loguru import logger
                logger.info("Starting HttpServer from RuntimeOwner...")
                await http_server.start()
        except BaseException:  # noqa: BROAD_EXCEPT_OK
            await self.stop()
            raise
        if self._config is not None and self._config.settings.kateto.hot_reload:
            controller = HotReloadController(
                manager=self._manager,
                watched_root=self._config.paths.config_dir,
                source_roots=(Path(__file__).resolve().parent / "plugins",),
                config=self._config,
                shared=self._shared,
            )
            await controller.start()
            self._hot_reload = controller
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
            controller = self._hot_reload
            self._hot_reload = None
            if controller is not None:
                await controller.close()
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


def build_runtime_owner(
    config: LoadedConfig,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> RuntimeOwner:
    resolved_dependencies = RuntimeDependencies() if dependencies is None else dependencies
    shared = resolved_dependencies.shared
    if shared is None:
        shared = {}
    manager, runtime_plugins = build_event_runtime(config, shared=shared)
    return RuntimeOwner(
        manager=manager,
        plugins=runtime_plugins,
        config=config,
        shared=shared,
        components=RuntimeComponents(
            plugins=(),
            mcp_servers=shared.get("mcp_servers") or (),
            workflow_voices=tuple(config.settings.voice.keys()),
            external_mcp=shared.get("external_mcp"),
            http_server=shared.get("http_server"),
        ),
    )


async def run_event_runtime(
    config: LoadedConfig,
    *,
    dependencies: RuntimeDependencies | None = None,
) -> None:
    _configure_logging(config)
    owner = build_runtime_owner(config, dependencies=dependencies)
    await owner.start()
    try:
        _ = await asyncio.Event().wait()
    finally:
        await owner.stop()
