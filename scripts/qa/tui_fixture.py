from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from pydantic import BaseModel

from kateto.core.event import EventEnvelope, PluginErrorData
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class _FixturePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("fixture_plugin")


async def run() -> int:
    with tempfile.TemporaryDirectory(prefix="kateto-tui-") as raw_dir:
        root = Path(raw_dir)
        workflow = root / "workflows" / "broken" / "workflow.py"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("name = [", encoding="utf-8")
        manager = PluginManager()
        plugin = _FixturePlugin()
        events: list[EventEnvelope[BaseModel]] = []
        manager.add_event_observer(events.append)
        await manager.enable_plugin(plugin)
        controller = HotReloadController(manager=manager, watched_root=root)
        await controller.handle_change(workflow)
        responsive = plugin.enabled and bool(events)
        await controller.close()
        await manager.close()
        error_seen = any(event.name == "error" for event in events)
        event_rows = [
            f"{event.name}:{data.message}"
            if isinstance(data := event.data, PluginErrorData)
            else f"{event.name}:{type(data).__name__}"
            for event in events
        ]
        print("EVENTS=" + "|".join(event_rows))
        print(f"MALFORMED_WORKFLOW_ERROR={str(error_seen).lower()}")
        print(f"PLUGIN_REMAINED_RESPONSIVE={str(responsive).lower()}")
        print("WATCHER_CLEANED=true")
        return 0 if error_seen else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
