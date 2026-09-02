import asyncio
import time
import pytest

from kateto.core.event import EventModel, InterruptData
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.config import PluginSettings
from kateto.plugins.audio_output.edgetts import EdgeTTSAudioOutput
from kateto.plugins.audio_output.player import AudioOutputPlayer
from kateto.tests.test_edgetts_interruption import DummyEdgeTTSProvider


class WorkData(EventModel):
    duration: float


class SlowWorkerPlugin(Plugin):
    def __init__(self, name: str = "slow_worker") -> None:
        super().__init__(name=name)
        self.processed = 0

    async def initialize(self) -> None:
        self.required_manager.register_event("work", WorkData)

    async def on_work(self, data: WorkData) -> None:
        await asyncio.sleep(data.duration)
        self.processed += 1

    async def on_interrupt(self, data: InterruptData) -> None:
        del data
        self.clear_queue()


@pytest.mark.asyncio
async def test_plugin_wait_idle_awaits_queued_work() -> None:
    manager = PluginManager()
    worker = SlowWorkerPlugin()
    manager.register_plugin(worker)
    await manager.enable_plugin(worker)

    assert worker.is_busy is False
    assert await worker.wait_idle(timeout=0.1) is True

    # When: Enqueue slow work (0.15s)
    await manager.emit("work", WorkData(duration=0.15), source="test")
    await asyncio.sleep(0.01)

    # Then: Plugin is busy
    assert worker.is_busy is True

    t0 = time.monotonic()
    idle_reached = await worker.wait_idle(timeout=1.0)
    elapsed = time.monotonic() - t0

    assert idle_reached is True
    assert elapsed >= 0.12
    assert worker.is_busy is False
    assert worker.processed == 1

    await manager.close()


@pytest.mark.asyncio
async def test_plugin_wait_idle_unblocks_immediately_on_interrupt() -> None:
    manager = PluginManager()
    worker = SlowWorkerPlugin()
    manager.register_plugin(worker)
    await manager.enable_plugin(worker)

    # Enqueue multiple work items
    await manager.emit("work", WorkData(duration=0.5), source="test")
    await manager.emit("work", WorkData(duration=0.5), source="test")
    await asyncio.sleep(0.01)
    assert worker.is_busy is True

    # When: Interrupt is fired shortly after starting
    async def _fire_interrupt():
        await asyncio.sleep(0.05)
        await manager.emit("interrupt", InterruptData(reason="objection"), source="test")

    task = asyncio.create_task(_fire_interrupt())

    t0 = time.monotonic()
    await worker.wait_idle(timeout=2.0)
    elapsed = time.monotonic() - t0
    await task

    # Then: It unblocked in much less than the 1.0s of total work
    assert elapsed < 0.75

    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_and_player_wait_idle_lifecycle() -> None:
    manager = PluginManager()
    provider = DummyEdgeTTSProvider()
    settings = PluginSettings(enabled=True)
    edgetts = EdgeTTSAudioOutput(settings, provider=provider, default_voice="es-AR-ElenaNeural")
    player = AudioOutputPlayer(settings)

    manager.register_plugin(edgetts)
    manager.register_plugin(player)
    await manager.enable_plugin(edgetts)
    await manager.enable_plugin(player)

    # Initial state
    assert edgetts.is_busy is False
    assert player.is_busy is False
    assert await edgetts.wait_idle(timeout=0.1) is True
    assert await player.wait_idle(timeout=0.1) is True

    # Interrupt unblocks both immediately
    await manager.emit("interrupt", InterruptData(reason="objection"), source="test")
    assert await edgetts.wait_idle(timeout=0.1) is True
    assert await player.wait_idle(timeout=0.1) is True

    await manager.close()
