from __future__ import annotations

from kateto.core.discovery import DiscoveryContext
from kateto.core.plugin import Plugin
from kateto.plugins.mask_camera.camera_plugin import MaskCameraPlugin


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    settings = ctx.config.settings.plugin.get("mask_camera")
    if settings is not None and not settings.enabled:
        return ()
    return (MaskCameraPlugin(settings=settings),)
