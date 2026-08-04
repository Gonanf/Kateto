"""System discovery entry point: always-on core plugins + non-plugin services.

``_scan_plugins`` in ``kateto/core/discovery.py`` imports every
``kateto/plugins/*/__init__.py`` and calls its ``create_plugins(ctx)`` factory.
This module is that factory for the system plugins: it builds the runtime
services that are NOT ``Plugin`` instances (external MCP manager, internal MCP
event servers, HTTP server) into ``ctx.shared``, then returns the always-on
core plugins (``VoiceManager``, ``WorkflowEngine``) for discovery.
"""

from __future__ import annotations

from kateto.core.discovery import DiscoveryContext
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow_engine import WorkflowEngine
from kateto.plugins.system.external_mcp import ExternalMcpManager
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.system.mcp_server import McpEventServer, McpServerOptions
from kateto.plugins.system.voice_manager import VoiceManager


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    """Create the system plugins and stash non-plugin services in ``ctx.shared``.

    ``VoiceManager`` and ``WorkflowEngine`` are always-on and need no
    ``[plugin.*]`` settings; MCP/HTTP services are config-gated.
    """
    manager: PluginManager | None = ctx.get_shared("manager")

    # External MCP clients, exposed via shared so the voice factory finds them.
    external_mcp: ExternalMcpManager = ctx.get_shared("external_mcp", ExternalMcpManager)
    for voice_name, voice in ctx.config.settings.voice.items():
        if not voice.enabled:
            continue
        for server_name in voice.mcp_servers:
            if server_name == "system":
                continue
            server_settings = ctx.config.settings.mcp_servers.get(server_name)
            if server_settings is not None:
                external_mcp.configure(voice_name, server_name, server_settings)

    if manager is not None:
        ctx.shared["mcp_servers"] = tuple(
            McpEventServer(
                manager,
                ctx.config.settings,
                McpServerOptions(server_name=server_name, voice_name=voice_name),
                config_dir=ctx.config.paths.config_dir,
            )
            for voice_name, voice in ctx.config.settings.voice.items()
            if voice.enabled
            for server_name in voice.mcp_servers
            if server_name == "system"
        )
        http_settings = ctx.config.settings.plugin.get("http_server")
        if http_settings is not None and http_settings.enabled:
            host = http_settings.host or "127.0.0.1"
            port = http_settings.port or 8080
            ctx.get_shared("http_server", lambda: HttpServer(manager, host=host, port=port))

    voice_manager_settings = ctx.config.settings.plugin.get("voice_manager")
    voice_manager = VoiceManager(
        voice_manager_settings if voice_manager_settings is not None else None
    )
    workflow_engine = WorkflowEngine(config_dir=ctx.config.paths.config_dir)
    return voice_manager, workflow_engine
