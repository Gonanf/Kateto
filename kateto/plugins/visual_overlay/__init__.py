from __future__ import annotations

from kateto.core.discovery import DiscoveryContext
from kateto.core.plugin import Plugin
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    settings = ctx.config.settings.plugin.get("visual_overlay")
    if settings is not None and not settings.enabled:
        return ()
    return (VisualOverlayPlugin(),)
