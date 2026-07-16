from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Final
from pydantic import BaseModel

from .event import EventEnvelope, InterruptData, PluginErrorData
from .plugin import Plugin

log = logging.getLogger("kateto.manager")

EventHandler = Callable[[BaseModel], Awaitable[None]]
Subscriber = tuple[str, EventHandler]
EventObserver = Callable[[EventEnvelope[BaseModel]], None]
DEFAULT_EVENT_LIMIT: Final = 1_000


@dataclass(frozen=True, slots=True)
class EventRegistration:
    name: str
    contract: type[BaseModel]
    receivers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PluginEventHistory:
    sent: tuple[EventEnvelope[BaseModel], ...]
    received: tuple[EventEnvelope[BaseModel], ...]


class PluginManager:
    def __init__(self, *, event_limit: int = DEFAULT_EVENT_LIMIT) -> None:
        if event_limit < 0:
            msg = "event limit must not be negative"
            raise ValueError(msg)
        self._plugins: dict[str, Plugin] = {}
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._contracts: dict[str, type[BaseModel]] = {
            "error": PluginErrorData,
            "interrupt": InterruptData,
        }
        self._events: deque[EventEnvelope[BaseModel]] = deque(maxlen=event_limit)
        self._sent_events: dict[str, deque[EventEnvelope[BaseModel]]] = {}
        self._received_events: dict[str, deque[EventEnvelope[BaseModel]]] = {}
        self._event_limit: int = event_limit
        self._event_observers: list[EventObserver] = []
        self._dispatch_tasks: set[asyncio.Task[None]] = set()
        self._completed_dispatches = 0

    def register_event(self, name: str, contract: type[BaseModel]) -> None:
        if not name:
            msg = "event name must not be empty"
            raise ValueError(msg)
        if not issubclass(contract, BaseModel):
            msg = "event contracts must be Pydantic models"
            raise TypeError(msg)
        self._contracts[name] = contract

    async def enable_plugin(self, plugin: Plugin) -> None:
        existing = self._plugins.get(plugin.name)
        if existing is not None and existing is not plugin:
            msg = f"plugin already registered: {plugin.name}"
            raise ValueError(msg)
        if plugin.enabled:
            return
        plugin.manager = self
        if not plugin._initialized:
            await plugin.initialize()
            plugin._initialized = True
        await plugin.enable()
        plugin.enabled = True
        self._plugins[plugin.name] = plugin
        self._remove_subscribers(plugin.name)
        for event_name, handler in plugin.iter_event_handlers().items():
            self._subscribers.setdefault(event_name, []).append((plugin.name, handler))
        plugin._start_worker()

    async def disable_plugin(self, name: str) -> None:
        plugin = self._plugins.get(name)
        if plugin is None or not plugin.enabled:
            return
        self._remove_subscribers(name)
        plugin.enabled = False
        await plugin._stop_worker()
        await plugin.disable()

    async def replace_plugin(self, current: Plugin, replacement: Plugin) -> None:
        if current is replacement:
            msg = "replacement plugin must be a distinct object"
            raise ValueError(msg)
        if current.name != replacement.name:
            msg = "replacement plugin name must match the active plugin"
            raise ValueError(msg)
        if self._plugins.get(current.name) is not current:
            msg = f"plugin is not active: {current.name}"
            raise ValueError(msg)
        await self.disable_plugin(current.name)
        self._plugins[current.name] = replacement
        await self.enable_plugin(replacement)

    async def close(self) -> None:
        for name in tuple(self._plugins):
            await self.disable_plugin(name)

    def get_plugins(self) -> tuple[Plugin, ...]:
        return tuple(self._plugins.values())

    def get_events(self) -> tuple[EventEnvelope[BaseModel], ...]:
        return tuple(self._events)

    def get_plugin_event_history(self, plugin_name: str) -> PluginEventHistory:
        return PluginEventHistory(
            sent=tuple(self._sent_events.get(plugin_name, ())),
            received=tuple(self._received_events.get(plugin_name, ())),
        )

    def get_event_registrations(self) -> tuple[EventRegistration, ...]:
        return tuple(
            EventRegistration(
                name=name,
                contract=contract,
                receivers=tuple(plugin_name for plugin_name, _ in self._subscribers.get(name, ())),
            )
            for name, contract in self._contracts.items()
        )

    def add_event_observer(self, observer: EventObserver) -> None:
        if observer not in self._event_observers:
            self._event_observers.append(observer)

    def remove_event_observer(self, observer: EventObserver) -> None:
        if observer in self._event_observers:
            self._event_observers.remove(observer)

    async def interrupt(
        self,
        *,
        target: str | None = None,
        reason: str = "voice_activity",
        source: str = "plugin_manager",
    ) -> EventEnvelope[BaseModel]:
        return await self.emit(
            "interrupt",
            InterruptData(reason=reason),
            source=source,
            target=target,
        )

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
    ) -> EventEnvelope[BaseModel]:
        capability_filter = self._validate_filters(target, capabilities)
        if not isinstance(data, BaseModel):
            msg = "event payload must be a Pydantic model"
            raise TypeError(msg)
        contract = self._contracts.get(name)
        if contract is not None and not isinstance(data, contract):
            msg = f"{name} requires {contract.__name__}"
            raise TypeError(msg)
        envelope = EventEnvelope[BaseModel](
            name=name,
            data=data,
            source=source,
            target=target,
            capabilities=list(capability_filter) or None,
            only_once=only_once,
            reply_to=reply_to,
            correlation_id=correlation_id,
        )
        self._events.append(envelope)
        self._history_for(self._sent_events, envelope.source.split("/", maxsplit=1)[0]).append(envelope)
        log.debug("emit %s source=%s target=%s", name, source, target or "*")
        for observer in tuple(self._event_observers):
            observer(envelope)
        recipients = self._resolve_subscribers(envelope, capability_filter)
        if only_once:
            recipients = recipients[:1]
        log.debug("dispatch %s to %s", name, [p.name for p, _ in recipients])
        for plugin, handler in recipients:
            self._history_for(self._received_events, plugin.name).append(envelope)
            task = asyncio.create_task(plugin._enqueue(envelope, handler))
            self._dispatch_tasks.add(task)
            task.add_done_callback(self._complete_dispatch)
        return envelope

    async def wait_for_idle(self, *, timeout: float = 5) -> None:
        try:
            async with asyncio.timeout(timeout):
                while True:
                    completed_before = self._completed_dispatches
                    if self._dispatch_tasks:
                        await asyncio.gather(*tuple(self._dispatch_tasks))
                    enabled_plugins = tuple(plugin for plugin in self._plugins.values() if plugin.enabled)
                    if enabled_plugins:
                        await asyncio.gather(*(plugin.queue.join() for plugin in enabled_plugins))
                    await asyncio.sleep(0)
                    if not self._dispatch_tasks and completed_before == self._completed_dispatches:
                        return
        except TimeoutError as error:
            msg = f"plugin manager did not become idle within {timeout} seconds"
            raise TimeoutError(msg) from error

    def _complete_dispatch(self, task: asyncio.Task[None]) -> None:
        self._dispatch_tasks.discard(task)
        self._completed_dispatches += 1

    def _history_for(
        self,
        histories: dict[str, deque[EventEnvelope[BaseModel]]],
        plugin_name: str,
    ) -> deque[EventEnvelope[BaseModel]]:
        history: deque[EventEnvelope[BaseModel]] | None = histories.get(plugin_name)
        if history is None:
            history = deque(maxlen=self._event_limit)
            histories[plugin_name] = history
        return history

    async def _report_plugin_error(
        self,
        plugin: Plugin,
        envelope: EventEnvelope[BaseModel],
        error: Exception,
    ) -> None:
        if envelope.name != "error":
            await self.emit(
                "error",
                PluginErrorData(
                    plugin=plugin.name,
                    event_name=envelope.name,
                    error_type=type(error).__name__,
                    message=str(error),
                ),
                source=plugin.name,
                target=envelope.reply_to,
                reply_to=envelope.reply_to,
                correlation_id=envelope.correlation_id,
            )

    def _remove_subscribers(self, plugin_name: str) -> None:
        for event_name, subscribers in tuple(self._subscribers.items()):
            remaining = [subscriber for subscriber in subscribers if subscriber[0] != plugin_name]
            if remaining:
                self._subscribers[event_name] = remaining
            else:
                del self._subscribers[event_name]

    def _resolve_subscribers(
        self,
        envelope: EventEnvelope[BaseModel],
        capabilities: tuple[str, ...],
    ) -> list[tuple[Plugin, EventHandler]]:
        source_plugin = envelope.source.split("/", maxsplit=1)[0]
        matching: list[tuple[Plugin, EventHandler]] = []
        for plugin_name, handler in self._subscribers.get(envelope.name, []):
            plugin = self._plugins.get(plugin_name)
            if plugin is None or not plugin.enabled:
                continue
            if plugin_name == source_plugin and not plugin.receive_self_events:
                continue
            if envelope.target is not None and plugin_name != envelope.target:
                continue
            if capabilities and not all(capability in plugin.capabilities for capability in capabilities):
                continue
            matching.append((plugin, handler))
        return matching

    def _validate_filters(
        self,
        target: str | None,
        capabilities: Iterable[str],
    ) -> tuple[str, ...]:
        if isinstance(capabilities, str):
            msg = "capabilities must be an iterable of names"
            raise TypeError(msg)
        try:
            capability_filter = tuple(capabilities)
        except TypeError as error:
            msg = "capabilities must be an iterable of names"
            raise TypeError(msg) from error
        if any(not isinstance(capability, str) for capability in capability_filter):
            msg = "capabilities must contain only strings"
            raise TypeError(msg)
        if target is not None and capability_filter:
            msg = "target and capabilities are mutually exclusive"
            raise ValueError(msg)
        if target == "":
            msg = "target must not be empty"
            raise ValueError(msg)
        if any(not capability for capability in capability_filter):
            msg = "capabilities must not contain empty names"
            raise ValueError(msg)
        return capability_filter


_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
