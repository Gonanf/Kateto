from __future__ import annotations

from hipotenusa.core.discovery import DiscoveryContext
from hipotenusa.core.plugin import Plugin
from hipotenusa.plugins.mask_camera.camera_plugin import MaskCameraPlugin


def create_plugins(ctx: DiscoveryContext) -> tuple[Plugin, ...]:
    settings = ctx.config.settings.plugin.get("mask_camera")
    if settings is not None and not settings.enabled:
        return ()
    return (MaskCameraPlugin(settings=settings),)
