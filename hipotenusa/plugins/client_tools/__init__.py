from __future__ import annotations

from hipotenusa.core.discovery import DiscoveryContext
from hipotenusa.core.plugin import Plugin
from hipotenusa.plugins.client_tools.client_tools_plugin import ClientToolsPlugin


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    return (ClientToolsPlugin(),)
