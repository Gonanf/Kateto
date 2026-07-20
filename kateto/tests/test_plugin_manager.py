from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

import kateto.core as core

from kateto.core import Plugin, PluginEventHistory, PluginManager, get_plugin_manager
from kateto.core.event import AudioData, AudioOutput, EventEnvelope, EventModel, GenerateData, InterruptData


class ContextData(EventModel):
    text: str


class CollectionData(EventModel):
    text: str
    values: list[int]
    metadata: dict[str, int]


class HistoryReceiver(Plugin):
    def __init__(self) -> None:
        super().__init__("receiver")
        self.audio_chunks: list[bytes] = []
        self.audio_outputs: list[bytes] = []
        self.contexts: list[str] = []
        self.delivered = asyncio.Event()

    async def on_audio_chunk(self, data: AudioData) -> None:
        self.audio_chunks.append(data.samples)
        self._mark_delivered()

    async def on_audio_output(self, data: AudioOutput) -> None:
        self.audio_outputs.append(data.samples)
        self._mark_delivered()

    async def on_context(self, data: ContextData) -> None:
        self.contexts.append(data.text)
        self._mark_delivered()

    def _mark_delivered(self) -> None:
        if len(self.audio_chunks) + len(self.audio_outputs) + len(self.contexts) == 3:
            self.delivered.set()


class LifecyclePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("lifecycle")
        self.transitions: list[str] = []
        self.received: list[str] = []
        self.delivered = asyncio.Event()

    async def initialize(self) -> None:
        self.transitions.append("initialize")

    async def enable(self) -> None:
        self.transitions.append("enable")

    async def disable(self) -> None:
        self.transitions.append("disable")

    async def on_context(self, data: ContextData) -> None:
        self.received.append(data.text)
        self.delivered.set()


class BatchPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("voice", streaming=False, batch_trigger="generate")
        self.batches: list[tuple[str, ...]] = []
        self.generated = asyncio.Event()
        self.interrupts: list[str] = []
        self.interrupted = asyncio.Event()

    async def on_context(self, data: ContextData) -> None:
        msg = "batch context must wait for generate"
        raise AssertionError(msg)

    async def on_generate(self, data: GenerateData) -> None:
        self.batches.append(tuple(event.name for event in self.batch_events))
        self.generated.set()

    async def on_interrupt(self, data: InterruptData) -> None:
        self.interrupts.append(data.reason)
        self.interrupted.set()


class BlockingPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("blocking")
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.completed = asyncio.Event()
        self.release = asyncio.Event()

    async def on_context(self, data: ContextData) -> None:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        self.completed.set()


def test_core_exports_preserve_event_contracts_and_add_plugin_api() -> None:
    # Given: the prior event-contract exports and the new plugin API.
    expected_exports = {
        "AudioData",
        "EventEnvelope",
        "Plugin",
        "PluginErrorData",
        "PluginManager",
        "WorkflowStopData",
        "get_plugin_manager",
    }

    # When: consumers inspect the core public export list.
    exported_names = set(core.__all__)

    # Then: existing contracts remain available alongside the event-bus API.
    assert expected_exports <= exported_names


@pytest.mark.asyncio
async def test_enable_scans_on_handlers_and_disable_removes_subscriptions() -> None:
    # Given: a plugin with an on_context handler and lifecycle hooks.
    manager = PluginManager()
    plugin = LifecyclePlugin()

    # When: it is enabled, receives an event, and is disabled.
    await manager.enable_plugin(plugin)
    await manager.emit("context", ContextData(text="first"), source="source")
    await plugin.delivered.wait()
    await manager.disable_plugin(plugin.name)
    await manager.emit("context", ContextData(text="ignored"), source="source")
    await manager.wait_for_idle()

    # Then: handler registration and lifecycle state are removed together.
    assert plugin.transitions == ["initialize", "enable", "disable"]
    assert plugin.received == ["first"]
    assert not plugin.enabled
    assert plugin.queue.empty()
    await manager.close()


@pytest.mark.asyncio
async def test_reenable_does_not_leave_a_stale_duplicate_subscriber() -> None:
    # Given: a plugin that has been enabled and then disabled.
    manager = PluginManager()
    plugin = LifecyclePlugin()
    await manager.enable_plugin(plugin)
    await manager.disable_plugin(plugin.name)

    # When: the same plugin instance is re-enabled and receives one event.
    await manager.enable_plugin(plugin)
    await manager.emit("context", ContextData(text="second"), source="source")
    await plugin.delivered.wait()
    await manager.wait_for_idle()

    # Then: it is registered exactly once without repeating initialization.
    assert plugin.transitions == ["initialize", "enable", "disable", "enable"]
    assert plugin.received == ["second"]
    await manager.close()


@pytest.mark.asyncio
async def test_batch_plugin_accumulates_until_its_generate_trigger() -> None:
    # Given: a batch plugin with context and generate handlers.
    manager = PluginManager()
    plugin = BatchPlugin()
    await manager.enable_plugin(plugin)

    # When: context arrives before the generate trigger.
    await manager.emit("context", ContextData(text="remember"), source="source")
    await manager.emit("generate", GenerateData(prompt="respond"), source="source")
    await plugin.generated.wait()
    await manager.wait_for_idle()

    # Then: the plugin sees a complete batch and does not process context early.
    assert plugin.batches == [("context", "generate")]
    assert plugin.batch_events == ()
    await manager.close()


@pytest.mark.asyncio
async def test_interrupt_bypasses_batch_accumulation_and_respects_target_routing() -> None:
    # Given: a batch plugin whose interrupt handler must be immediate.
    manager = PluginManager()
    voice = BatchPlugin()
    other = BatchPlugin()
    other.name = "other"
    await manager.enable_plugin(voice)
    await manager.enable_plugin(other)

    # When: an interrupt targets the first voice.
    await manager.interrupt(target="voice", reason="new-speech")
    await voice.interrupted.wait()
    await manager.wait_for_idle()

    # Then: the target receives it immediately without a generate trigger.
    assert voice.interrupts == ["new-speech"]
    assert other.interrupts == []
    assert voice.batch_events == ()
    await manager.close()


@pytest.mark.asyncio
async def test_disable_cancels_a_running_handler_and_reenable_resumes_processing() -> None:
    # Given: a plugin blocked inside a queued handler.
    manager = PluginManager()
    plugin = BlockingPlugin()
    await manager.enable_plugin(plugin)
    await manager.emit("context", ContextData(text="block"), source="source")
    await plugin.started.wait()

    # When: the plugin is disabled and enabled again.
    await manager.disable_plugin(plugin.name)
    await plugin.cancelled.wait()
    await manager.enable_plugin(plugin)
    plugin.release.set()
    await manager.emit("context", ContextData(text="resume"), source="source")
    await plugin.completed.wait()

    # Then: cancellation clears stale execution and later delivery can complete.
    assert plugin.queue.empty()
    assert plugin.enabled
    await manager.close()


@pytest.mark.asyncio
async def test_get_plugin_manager_returns_one_shared_singleton() -> None:
    # Given: two requests for the global manager.
    first = get_plugin_manager()

    # When: the accessor is called again.
    second = get_plugin_manager()

    # Then: both callers share the same event bus instance.
    assert first is second
    await first.close()


@pytest.mark.asyncio
async def test_event_history_is_bounded_and_exposes_plugin_sent_and_received_events() -> None:
    # Given: a manager with a finite history limit and a source/receiver pair.
    manager = PluginManager(event_limit=2)
    source = LifecyclePlugin()
    source.name = "source"
    receiver = LifecyclePlugin()
    receiver.name = "receiver"
    await manager.enable_plugin(source)
    await manager.enable_plugin(receiver)

    # When: the source emits more events than the manager can retain.
    envelopes = [
        await manager.emit("context", ContextData(text=str(index)), source="source")
        for index in range(3)
    ]
    await receiver.delivered.wait()
    await manager.wait_for_idle()

    # Then: global and per-plugin histories retain only the newest typed events.
    assert manager.get_events() == tuple(envelopes[-2:])
    history = manager.get_plugin_event_history("source")
    assert isinstance(history, PluginEventHistory)
    assert history.sent == tuple(envelopes[-2:])
    assert manager.get_plugin_event_history("receiver").received == tuple(envelopes[-2:])
    await manager.close()


@pytest.mark.asyncio
async def test_default_event_history_limit_is_finite() -> None:
    # Given: a manager using its default event-history configuration.
    manager = PluginManager()

    # When: more than the default retention limit is emitted.
    for index in range(1_001):
        await manager.emit("context", ContextData(text=str(index)), source="source")

    # Then: the default retains a finite recent window.
    assert len(manager.get_events()) == 1_000
    first = manager.get_events()[0].data
    last = manager.get_events()[-1].data
    assert isinstance(first, ContextData)
    assert isinstance(last, ContextData)
    assert first.text == "1"
    assert last.text == "1000"
    await manager.close()


@pytest.mark.asyncio
async def test_history_compacts_large_audio_payloads_but_preserves_dispatch_payloads() -> None:
    # Given: a manager retaining events and a receiver for audio and text events.
    manager = PluginManager()
    manager.register_event("audio_chunk", AudioData)
    manager.register_event("audio_output", AudioOutput)
    manager.register_event("collection", CollectionData)
    receiver = HistoryReceiver()
    observed: list[EventEnvelope[BaseModel]] = []
    manager.add_event_observer(observed.append)
    await manager.enable_plugin(receiver)
    audio_samples = b"input" * 20_000
    output_samples = b"output" * 20_000

    # When: large audio events and a normal text event are emitted.
    emitted = [
        await manager.emit(
            "audio_chunk",
            AudioData(samples=audio_samples, sample_rate=16_000),
            source="source",
        ),
        await manager.emit(
            "audio_output",
            AudioOutput(samples=output_samples, sample_rate=24_000, channels=1),
            source="source",
        ),
        await manager.emit("context", ContextData(text="hello"), source="source"),
        await manager.emit(
            "collection",
            CollectionData(
                text="x" * 5_000,
                values=list(range(129)),
                metadata={str(index): index for index in range(129)},
            ),
            source="source",
        ),
    ]
    await receiver.delivered.wait()
    await manager.wait_for_idle()

    # Then: handlers and observers receive the original payloads.
    assert receiver.audio_chunks == [audio_samples]
    assert receiver.audio_outputs == [output_samples]
    assert receiver.contexts == ["hello"]
    assert [envelope.data for envelope in observed] == [envelope.data for envelope in emitted]

    # Then: history retains typed envelopes without pinning large payloads.
    history = manager.get_plugin_event_history("source")
    assert isinstance(history.sent[0].data, AudioData)
    assert isinstance(history.sent[1].data, AudioOutput)
    assert isinstance(history.sent[2].data, ContextData)
    assert isinstance(history.sent[3].data, CollectionData)
    assert history.sent[0].data.samples == b""
    assert history.sent[1].data.samples == b""
    assert history.sent[2].data.text == "hello"
    assert history.sent[3].data.text == "<compacted 5000 character payload>"
    assert history.sent[3].data.values == []
    assert history.sent[3].data.metadata == {}
    events = manager.get_events()
    assert [event.name for event in events] == [event.name for event in emitted]
    assert isinstance(events[0].data, AudioData)
    assert isinstance(events[1].data, AudioOutput)
    assert isinstance(events[2].data, ContextData)
    assert events[0].data.samples == b""
    assert events[1].data.samples == b""
    assert events[2].data.text == "hello"
    assert isinstance(events[3].data, CollectionData)
    assert events[3].data.values == []
    await manager.close()
