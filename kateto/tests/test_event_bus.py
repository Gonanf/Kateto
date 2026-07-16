from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from kateto.core import Plugin, PluginErrorData, PluginManager
from kateto.core.event import EventModel, GenerateData


class PingData(EventModel):
    value: str


class RecordingPlugin(Plugin):
    def __init__(self, name: str, *, capabilities: tuple[str, ...] = ()) -> None:
        super().__init__(name, capabilities=capabilities)
        self.received: list[str] = []
        self.delivered = asyncio.Event()

    async def on_ping(self, data: PingData) -> None:
        self.received.append(data.value)
        self.delivered.set()


class GatedPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("gated")
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.release = asyncio.Event()

    async def on_ping(self, data: PingData) -> None:
        self.started.set()
        await self.release.wait()
        self.finished.set()


class CrashingPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("crashing")

    async def on_ping(self, data: PingData) -> None:
        msg = "boom"
        raise RuntimeError(msg)


class ErrorObserver(Plugin):
    def __init__(self) -> None:
        super().__init__("observer")
        self.errors: list[PluginErrorData] = []
        self.delivered = asyncio.Event()

    async def on_error(self, data: PluginErrorData) -> None:
        self.errors.append(data)
        self.delivered.set()


@pytest.mark.asyncio
async def test_broadcast_delivers_to_matching_subscribers_but_not_the_source() -> None:
    # Given: two registered plugins with the same event handler, one as the source.
    manager = PluginManager()
    publisher = RecordingPlugin("publisher")
    listener = RecordingPlugin("listener")
    await manager.enable_plugin(publisher)
    await manager.enable_plugin(listener)

    # When: the publisher emits a broadcast event.
    await manager.emit("ping", PingData(value="hello"), source="publisher")
    await listener.delivered.wait()
    await manager.wait_for_idle()

    # Then: only the non-source matching subscriber processes the event.
    assert publisher.received == []
    assert listener.received == ["hello"]
    await manager.close()


@pytest.mark.asyncio
async def test_target_routes_only_to_the_named_plugin() -> None:
    # Given: two enabled subscribers for the same event.
    manager = PluginManager()
    selected = RecordingPlugin("selected")
    skipped = RecordingPlugin("skipped")
    await manager.enable_plugin(selected)
    await manager.enable_plugin(skipped)

    # When: an event targets one subscriber by name.
    await manager.emit("ping", PingData(value="direct"), source="source", target="selected")
    await selected.delivered.wait()
    await manager.wait_for_idle()

    # Then: the target alone receives the event.
    assert selected.received == ["direct"]
    assert skipped.received == []
    await manager.close()


@pytest.mark.asyncio
async def test_capability_filter_requires_every_capability() -> None:
    # Given: subscribers with overlapping but different capability sets.
    manager = PluginManager()
    matching = RecordingPlugin("matching", capabilities=("voice", "agent"))
    partial = RecordingPlugin("partial", capabilities=("voice",))
    await manager.enable_plugin(matching)
    await manager.enable_plugin(partial)

    # When: an event is filtered by two capabilities.
    await manager.emit(
        "ping",
        PingData(value="filtered"),
        source="source",
        capabilities=("voice", "agent"),
    )
    await matching.delivered.wait()
    await manager.wait_for_idle()

    # Then: only a subscriber with the complete capability set receives it.
    assert matching.received == ["filtered"]
    assert partial.received == []
    await manager.close()


@pytest.mark.asyncio
async def test_only_once_selects_the_first_matching_registration() -> None:
    # Given: two matching subscribers enabled in registration order.
    manager = PluginManager()
    first = RecordingPlugin("first")
    second = RecordingPlugin("second")
    await manager.enable_plugin(first)
    await manager.enable_plugin(second)

    # When: an only-once event is emitted.
    await manager.emit("ping", PingData(value="once"), source="source", only_once=True)
    await first.delivered.wait()
    await manager.wait_for_idle()

    # Then: only the first matching registration handles the event.
    assert first.received == ["once"]
    assert second.received == []
    await manager.close()


@pytest.mark.asyncio
async def test_emit_records_history_and_returns_before_a_handler_finishes() -> None:
    # Given: a subscriber whose handler remains blocked until explicitly released.
    manager = PluginManager()
    gated = GatedPlugin()
    await manager.enable_plugin(gated)

    # When: the manager emits an event.
    envelope = await manager.emit("ping", PingData(value="queued"), source="source")

    # Then: history is immediately available while handler completion remains pending.
    assert manager.get_events() == (envelope,)
    assert not gated.finished.is_set()
    await gated.started.wait()
    assert not gated.finished.is_set()
    gated.release.set()
    await gated.finished.wait()
    await manager.close()


@pytest.mark.asyncio
async def test_wait_for_idle_raises_timeout_when_subscriber_is_permanently_blocked() -> None:
    # Given: a subscriber that has started handling an event but never releases it.
    manager = PluginManager()
    gated = GatedPlugin()
    await manager.enable_plugin(gated)

    try:
        await manager.emit("ping", PingData(value="blocked"), source="source")
        await gated.started.wait()

        # When: the caller waits for the manager to become idle with a bounded deadline.
        with pytest.raises(TimeoutError, match="did not become idle"):
            async with asyncio.timeout(1):
                await manager.wait_for_idle(timeout=0.01)

        # Then: the blocked handler remains visible instead of making the caller wait forever.
        assert not gated.finished.is_set()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_crashing_plugin_emits_error_event_and_keeps_the_bus_running() -> None:
    # Given: one handler that crashes and an observer for error events.
    manager = PluginManager()
    crashing = CrashingPlugin()
    observer = ErrorObserver()
    healthy = RecordingPlugin("healthy")
    await manager.enable_plugin(crashing)
    await manager.enable_plugin(observer)
    await manager.enable_plugin(healthy)

    # When: the crashing handler receives a normal event.
    await manager.emit("ping", PingData(value="first"), source="source")
    await observer.delivered.wait()
    await manager.wait_for_idle()

    # Then: the error is observable and other subscribers still receive the event.
    assert observer.errors[0].plugin == "crashing"
    assert observer.errors[0].event_name == "ping"
    assert healthy.received == ["first"]
    assert manager.get_events()[-1].name == "error"
    await manager.close()


@pytest.mark.asyncio
async def test_malformed_payload_and_mutually_exclusive_filters_are_rejected() -> None:
    # Given: a manager with a registered Pydantic contract.
    manager = PluginManager()
    manager.register_event("ping", PingData)

    # When: callers provide the wrong Pydantic payload or two routing modes.
    with pytest.raises(TypeError, match="ping requires PingData"):
        await manager.emit("ping", GenerateData(), source="source")
    with pytest.raises(ValueError, match="mutually exclusive"):
        await manager.emit(
            "ping",
            PingData(value="invalid-filter"),
            source="source",
            target="target",
            capabilities=("voice",),
        )

    # Then: neither invalid dispatch enters event history.
    assert manager.get_events() == ()
    await manager.close()


@pytest.mark.asyncio
async def test_malformed_capability_filter_is_rejected_before_dispatch() -> None:
    # Given: a manager receiving a string instead of a capability collection.
    manager = PluginManager()

    # When: a caller supplies a malformed capability filter.
    with pytest.raises(TypeError, match="capabilities"):
        await manager.emit(
            "ping",
            PingData(value="invalid-capabilities"),
            source="source",
            capabilities="voice",
        )

    # Then: the malformed filter cannot become an event-history entry.
    assert manager.get_events() == ()
    await manager.close()


@pytest.mark.asyncio
async def test_concurrent_dispatch_delivers_each_event_once_without_a_hung_queue() -> None:
    # Given: a subscriber awaiting a finite concurrent burst.
    manager = PluginManager()
    receiver = RecordingPlugin("receiver")
    await manager.enable_plugin(receiver)

    # When: many emits are scheduled concurrently.
    await asyncio.gather(
        *(manager.emit("ping", PingData(value=str(index)), source="source") for index in range(20)),
    )
    await manager.wait_for_idle()

    # Then: every event is processed exactly once and the queue drains.
    assert sorted(receiver.received, key=int) == [str(index) for index in range(20)]
    assert receiver.queue.empty()
    await manager.close()


def test_bus_fixture_reports_broadcast_and_missing_target_outcomes() -> None:
    # Given: the package is available through its module fixture surface.
    command = [sys.executable, "-m", "kateto.qa.bus_fixture"]

    # When: users run the broadcast and missing-target scenarios.
    broadcast = subprocess.run(
        [*command, "--mode", "broadcast"],
        capture_output=True,
        check=False,
        text=True,
    )
    missing_target = subprocess.run(
        [*command, "--mode", "target", "--target", "missing"],
        capture_output=True,
        check=False,
        text=True,
    )

    # Then: both traces make the binary delivery outcome explicit.
    assert broadcast.returncode == 0, broadcast.stderr
    assert "deliveries=2" in broadcast.stdout
    assert missing_target.returncode == 0, missing_target.stderr
    assert "deliveries=0" in missing_target.stdout
    assert "manager_alive=true" in missing_target.stdout
