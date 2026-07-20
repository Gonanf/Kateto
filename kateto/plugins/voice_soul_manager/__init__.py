from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, override

from kateto.core.event import VoiceIdleData
from kateto.core.plugin import Plugin
from kateto.plugins.voice_soul_manager.scheduler import VoiceUpdateTracker
from kateto.plugins.voice_soul_manager.updater import VoiceUpdater

if TYPE_CHECKING:
    from kateto.core.discovery import DiscoveryContext


class VoiceSOULManager(Plugin):
    """Centralized manager for per-voice SOUL/JOURNAL maintenance.

    Listens for ``voice_idle`` events and, when a voice has been idle, auto-
    updates its JOURNAL.md (idle timestamp entry) and SOUL.md (last_active
    marker) subject to a time-based throttle.
    """

    def __init__(self, config_dir: Path) -> None:
        super().__init__("voice_soul_manager", streaming=True)
        self._config_dir = config_dir
        self._tracker = VoiceUpdateTracker()
        self._updater = VoiceUpdater(config_dir)

    @override
    async def initialize(self) -> None:
        # voice_idle is registered by VoiceAgent — nothing new to declare.
        return None

    @override
    async def enable(self) -> None:
        return None

    @override
    async def disable(self) -> None:
        self._tracker = VoiceUpdateTracker()

    async def on_voice_idle(self, data: VoiceIdleData) -> None:
        voice = data.voice
        if not self._tracker.should_update(voice):
            return
        await self._updater.append_idle_entry(voice)
        await self._updater.touch_soul(voice)
        self._tracker.mark_updated(voice)


def create_plugins(ctx: DiscoveryContext) -> list[Plugin]:
    settings = ctx.config.settings.plugin.get("voice_soul_manager")
    if settings is not None and not settings.enabled:
        return []
    return [VoiceSOULManager(config_dir=ctx.config.paths.config_dir)]
