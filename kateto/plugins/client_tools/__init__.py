from __future__ import annotations

from kateto.core.discovery import DiscoveryContext
from kateto.core.plugin import Plugin
from kateto.plugins.client_tools.client_tools_plugin import ClientToolsPlugin


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    return (ClientToolsPlugin(),)
