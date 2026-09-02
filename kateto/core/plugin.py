from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import inspect
from collections.abc import Awaitable, Callable
from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .event import EventEnvelope, InterruptData

if TYPE_CHECKING:
    from kateto.core.manager import PluginManager

EventHandler = Callable[[BaseModel], Awaitable[None]]
QueuedEvent = tuple[EventEnvelope[BaseModel], EventHandler]


class Plugin:
    immediate_events = frozenset({"interrupt"})

    @classmethod
    def register_config_param(cls, param_name: str, default: Any = None) -> None:
        """Register a parameter for this plugin's config section."""
        from kateto.core.config import register_plugin_param
        register_plugin_param(cls.__name__.lower(), param_name, default)

    @classmethod
    def register_voice_param(cls, param_name: str, default: Any = None) -> None:
        """Register a parameter that this plugin contributes to each voice's config."""
        from kateto.core.config import register_voice_param
        register_voice_param(param_name, default)

    def __init__(
        self,
        name: str,
        *,
        capabilities: tuple[str, ...] = (),
        depts: tuple[str, ...] = (),
        streaming: bool = True,
        batch_trigger: str = "generate",
        receive_self_events: bool = False,
    ) -> None:
        if not name:
            msg = "plugin name must not be empty"
            raise ValueError(msg)
        self.name = name
        self.capabilities = capabilities
        self.depts = tuple(dept.casefold() for dept in depts)
        self.streaming = streaming
        self.batch_trigger = batch_trigger
        self.receive_self_events = receive_self_events
        self.manager: PluginManager | None = None
        self.enabled = False
        self.queue: asyncio.Queue[QueuedEvent] = asyncio.Queue()
        self._batch_events: list[EventEnvelope[BaseModel]] = []
        self._current_envelope: EventEnvelope[BaseModel] | None = None
        self._initialized = False
        self._worker: asyncio.Task[None] | None = None
        self._consecutive_failures = 0
        self._idle_event: asyncio.Event = asyncio.Event()
        self._idle_event.set()

    @property
    def batch_events(self) -> tuple[EventEnvelope[BaseModel], ...]:
        return tuple(self._batch_events)

    @property
    def current_envelope(self) -> EventEnvelope[BaseModel] | None:
        return self._current_envelope

    @property
    def required_manager(self) -> PluginManager:
        manager = self.manager
        if manager is None:
            msg = f"{self.name} must be enabled before use"
            raise RuntimeError(msg)
        return manager

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

    @property
    def is_busy(self) -> bool:
        """Return True if this plugin is currently executing a handler or has queued work."""
        if not self.queue.empty() or self._current_envelope is not None:
            return True
        return False

    async def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until this plugin finishes processing all work and enters an idle state.

        Returns True if idle was reached, or False if timeout expired.
        Interruptable: if an interrupt occurs or work is aborted, this unblocks immediately.
        """
        if not self.is_busy:
            return True
        self._idle_event.clear()

        loop = asyncio.get_running_loop()
        start = loop.time()
        while self.is_busy:
            if timeout is not None:
                remaining = timeout - (loop.time() - start)
                if remaining <= 0:
                    return False
            else:
                remaining = None
            try:
                slice_timeout = min(remaining, 0.05) if remaining is not None else 0.05
                await asyncio.wait_for(self._idle_event.wait(), timeout=slice_timeout)
            except TimeoutError:
                if timeout is not None and (loop.time() - start) >= timeout:
                    return False
        return True

    async def _handle_immediate(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        try:
            data = envelope.data
            if isinstance(data, dict) and self.manager is not None:
                contract = self.manager.get_event_contract(envelope.name)
                if contract is not None:
                    data = contract.model_validate(data)
            await handler(data)
            self._consecutive_failures = 0
        except Exception as error:  # noqa: BROAD_EXCEPT_OK
            self._consecutive_failures += 1
            if self.manager is not None:
                await self.manager._report_plugin_error(self, envelope, error)
        finally:
            if not self.is_busy:
                self._idle_event.set()

    async def _enqueue(self, envelope: EventEnvelope[BaseModel], handler: EventHandler) -> None:
        if self.enabled:
            if envelope.name in self.immediate_events:
                _ = asyncio.create_task(
                    self._handle_immediate(envelope, handler),
                    name=f"kateto-immediate-{self.name}-{envelope.name}",
                )
                return
            self._idle_event.clear()
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
        self._idle_event.set()

    def clear_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.queue.task_done()
        if not self.is_busy:
            self._idle_event.set()

    async def _run(self) -> None:
        while True:
            envelope, handler = await self.queue.get()
            self._idle_event.clear()
            self._current_envelope = envelope
            try:
                data = envelope.data
                if isinstance(data, dict) and self.manager is not None:
                    contract = self.manager.get_event_contract(envelope.name)
                    if contract is not None:
                        data = contract.model_validate(data)
                if self.streaming or envelope.name in self.immediate_events:
                    await handler(data)
                else:
                    self._batch_events.append(envelope)
                    if envelope.name == self.batch_trigger:
                        try:
                            await handler(data)
                        finally:
                            self._batch_events.clear()
                self._consecutive_failures = 0
            except Exception as error:  # noqa: BROAD_EXCEPT_OK
                self._consecutive_failures += 1
                if self.manager is not None:
                    if self._consecutive_failures >= 5:
                        await self.manager._auto_disable_plugin(self, error)
                    else:
                        await self.manager._report_plugin_error(self, envelope, error)
            finally:
                self._current_envelope = None
                self.queue.task_done()
                if not self.is_busy:
                    self._idle_event.set()
