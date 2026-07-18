from __future__ import annotations

from kateto.core.event import AudioData, InterruptData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager


class InterruptExecutor(Plugin):
    def __init__(self) -> None:
        super().__init__("executor_interrupt")
        self._interrupted = False

    async def initialize(self) -> None:
        manager = self._manager()
        manager.register_event("audio_chunk", AudioData)
        manager.register_event("conversation_interrupted", InterruptData)
        manager.register_event("conversation_resumed", AudioData)

    async def on_interrupt(self, data: InterruptData) -> None:
        manager = self._manager()
        for plugin in manager.get_plugins():
            if plugin is self:
                continue
            handler = plugin.iter_event_handlers().get("interrupt")
            if handler is not None:
                await handler(data)
        if self._interrupted:
            return
        self._interrupted = True
        await manager.emit("conversation_interrupted", data, source=self.name)

    async def on_audio_chunk(self, data: AudioData) -> None:
        if not self._interrupted:
            return
        self._interrupted = False
        await self._manager().emit("conversation_resumed", data, source=self.name)

    def _manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = "interrupt executor must be enabled before use"
            raise RuntimeError(msg)
        return manager
