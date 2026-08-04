from unittest.mock import AsyncMock

import pytest

from kateto.core.event import ScheduleRequestData, ScheduleType
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class ScheduleOnInitPlugin(Plugin):
    """Plugin that emits a schedule_request in its enable method."""

    def __init__(self, name: str = "schedule_on_init_plugin") -> None:
        super().__init__(name=name, capabilities=("scheduling",))

    async def enable(self) -> None:
        await super().enable()
        # Emit schedule request when enabled
        await self.required_manager.emit(
            "schedule_request",
            ScheduleRequestData(
                schedule_type=ScheduleType.INTERVAL,
                expression="60s",
                event_name="heartbeat_ping",
            ),
            source=self.name,
        )


class ListenerPlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(name="listener")
        self.received = []

    async def on_schedule_request(self, data: ScheduleRequestData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_plugin_emit_on_enable_pattern():
    manager = PluginManager()
    manager.register_event("schedule_request", ScheduleRequestData)

    listener = ListenerPlugin()
    sender = ScheduleOnInitPlugin()

    await manager.enable_plugin(listener)
    await manager.enable_plugin(sender)
    await manager.wait_for_idle()

    assert len(listener.received) == 1
    req = listener.received[0]
    assert req.event_name == "heartbeat_ping"
    assert req.schedule_type == ScheduleType.INTERVAL

    await manager.disable_plugin(sender.name)
    await manager.disable_plugin(listener.name)
