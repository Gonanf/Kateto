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
    """Listener for ``voice_idle`` kept for runtime-shape stability.

    SOUL.md and JOURNAL.md are read-only at runtime (memory-ledger feature):
    declarative memories are written to the per-department VoiceMemoryLedger
    via the refine_memory tool, and the SOUL only changes between sessions via
    versioned snapshots. The updater calls below are no-ops, so the event
    subscription and throttle tracker stay in place for future session-boundary
    work.
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
    return [VoiceSOULManager(config_dir=ctx.config.paths.config_dir)]
