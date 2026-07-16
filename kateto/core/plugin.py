from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import inspect
from collections.abc import Awaitable, Callable
from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel

from .event import EventEnvelope, InterruptData

EventHandler = Callable[[BaseModel], Awaitable[None]]
QueuedEvent = tuple[EventEnvelope[BaseModel], EventHandler]


class PluginManagerProtocol(Protocol):
    def register_event(self, name: str, contract: type[BaseModel]) -> None: ...

    def get_plugins(self) -> tuple[Plugin, ...]: ...

    async def emit(
        self,
        name: str,
        data: BaseModel,
        *,
        source: str = "plugin_manager",
        target: str | None = None,
        capabilities: Iterable[str] = (),
        only_once: bool = False,
        reply_to: str | None = None,
        correlation_id: str | None = None,
    ) -> EventEnvelope[BaseModel]: ...

    async def interrupt(
        self,
        *,
        target: str | None = None,
        reason: str = "voice_activity",
        source: str = "plugin_manager",
    ) -> EventEnvelope[BaseModel]: ...

    async def _report_plugin_error(
        self,
        plugin: Plugin,
        envelope: EventEnvelope[BaseModel],
        error: Exception,
    ) -> None: ...


class Plugin:
    immediate_events = frozenset({"interrupt"})

    def __init__(
        self,
        name: str,
        *,
        capabilities: tuple[str, ...] = (),
        streaming: bool = True,
        batch_trigger: str = "generate",
        receive_self_events: bool = False,
    ) -> None:
        if not name:
            msg = "plugin name must not be empty"
            raise ValueError(msg)
        self.name = name
        self.capabilities = capabilities
        self.streaming = streaming
        self.batch_trigger = batch_trigger
        self.receive_self_events = receive_self_events
        self.manager: PluginManagerProtocol | None = None
        self.enabled = False
        self.queue: asyncio.Queue[QueuedEvent] = asyncio.Queue()
        self._batch_events: list[EventEnvelope[BaseModel]] = []
        self._current_envelope: EventEnvelope[BaseModel] | None = None
        self._initialized = False
        self._worker: asyncio.Task[None] | None = None

    @property
    def batch_events(self) -> tuple[EventEnvelope[BaseModel], ...]:
        return tuple(self._batch_events)

    @property
    def current_envelope(self) -> EventEnvelope[BaseModel] | None:
        return self._current_envelope

    async def initialize(self) -> None:
        return None

    async def enable(self) -> None:
        return None

    async def disable(self) -> None:
        return None

    def iter_event_handlers(self) -> dict[str, EventHandler]:
        handlers: dict[str, EventHandler] = {}
        for attribute_name in dir(self):
            if not attribute_name.startswith("on_"):
                continue
            event_name = attribute_name.removeprefix("on_")
            handler = getattr(self, attribute_name)
            if event_name and inspect.iscoroutinefunction(handler):
                handlers[event_name] = handler
        return handlers

    async def _enqueue(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        if self.enabled:
            await self.queue.put((envelope, handler))

    def _start_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run(), name=f"kateto-plugin-{self.name}")

    async def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker is not asyncio.current_task():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                worker.cancelled()
        self.clear_queue()
        self._batch_events.clear()

    def clear_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            self.queue.task_done()

    async def _run(self) -> None:
        while True:
            envelope, handler = await self.queue.get()
            self._current_envelope = envelope
            try:
                if self.streaming or envelope.name in self.immediate_events:
                    await handler(envelope.data)
                else:
                    self._batch_events.append(envelope)
                    if envelope.name == self.batch_trigger:
                        try:
                            await handler(envelope.data)
                        finally:
                            self._batch_events.clear()
            except Exception as error:  # noqa: BROAD_EXCEPT_OK
                if self.manager is not None:
                    await self.manager._report_plugin_error(self, envelope, error)
            finally:
                self._current_envelope = None
                self.queue.task_done()
