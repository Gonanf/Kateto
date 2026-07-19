"""Test: hot reload should not replace plugins that haven't changed.

Bug #15: _refresh_discovered replaces ALL plugins on any .py file change,
even when only one plugin's source changed. This kills active LLM workers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pydantic import BaseModel

from kateto.core.discovery import PluginRegistry
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class _TestEventData(BaseModel):
    payload: str = "ping"


class _StablePlugin(Plugin):
    """Plugin that should NOT be replaced when unrelated files change."""

    def __init__(self) -> None:
        super().__init__("stable_plugin", streaming=True)
        self.worker_cancelled = False

    async def on_test_event(self, data: _TestEventData) -> None:
        pass


class _ChangingPluginV1(Plugin):
    """Plugin version 1."""

    def __init__(self) -> None:
        super().__init__("changing_plugin", streaming=True)
        self.version = "v1"

    async def on_test_event(self, data: _TestEventData) -> None:
        pass


class _ChangingPluginV2(Plugin):
    """Plugin version 2 — different class definition."""

    def __init__(self) -> None:
        super().__init__("changing_plugin", streaming=True)
        self.version = "v2"

    async def on_test_event(self, data: _TestEventData) -> None:
        pass


def _write_config(root: Path) -> None:
    (root / "config.toml").write_text(
        "[kateto]\n\n[cli]\nallowlist = [\"echo\"]\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_hot_reload_does_not_replace_unchanged_plugins(tmp_path: Path) -> None:
    """When discovery returns same class, skip replacement."""
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)

    stable = _StablePlugin()
    await manager.enable_plugin(stable)
    stable_id = id(stable)

    replaced: list[str] = []
    original_replace = manager.replace_plugin

    async def tracked_replace(plugin, replacement):
        replaced.append(plugin.name)
        return await original_replace(plugin, replacement)

    manager.replace_plugin = tracked_replace  # type: ignore

    def discover(config: object) -> PluginRegistry:
        return PluginRegistry(plugins=frozenset({_StablePlugin()}))

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        discovery_factory=discover,
        replacement_factory=lambda p, c: _StablePlugin(),
    )

    trigger = tmp_path / "some_module.py"
    trigger.write_text("# change", encoding="utf-8")
    await controller.handle_change(trigger)

    assert "stable_plugin" not in replaced, (
        f"stable_plugin was unnecessarily replaced! Replaced: {replaced}"
    )
    plugins_by_name = {p.name: p for p in manager.get_plugins()}
    assert id(plugins_by_name["stable_plugin"]) == stable_id

    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_preserves_active_workers_during_replace(tmp_path: Path) -> None:
    """When discovery returns same class, worker should not be cancelled."""
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)

    stable = _StablePlugin()
    await manager.enable_plugin(stable)

    async def long_task():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stable.worker_cancelled = True
            raise

    stable.worker_task = asyncio.create_task(long_task())  # type: ignore

    def discover(config: object) -> PluginRegistry:
        return PluginRegistry(plugins=frozenset({_StablePlugin()}))

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        discovery_factory=discover,
        replacement_factory=lambda p, c: _StablePlugin(),
    )

    trigger = tmp_path / "some_module.py"
    trigger.write_text("# change", encoding="utf-8")
    await controller.handle_change(trigger)
    await asyncio.sleep(0.5)

    assert not stable.worker_cancelled, "stable_plugin's worker was cancelled!"
    assert not stable.worker_task.done()

    stable.worker_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stable.worker_task

    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_replaces_when_class_changes(tmp_path: Path) -> None:
    """When discovery returns a different class, replacement occurs."""
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)

    stable = _StablePlugin()
    changing_v1 = _ChangingPluginV1()
    await manager.enable_plugin(stable)
    await manager.enable_plugin(changing_v1)

    replaced: list[str] = []
    original_replace = manager.replace_plugin

    async def tracked_replace(plugin, replacement):
        replaced.append(plugin.name)
        return await original_replace(plugin, replacement)

    manager.replace_plugin = tracked_replace  # type: ignore

    # Discovery returns _ChangingPluginV2 — different class from _ChangingPluginV1
    def discover(config: object) -> PluginRegistry:
        return PluginRegistry(plugins=frozenset({_StablePlugin(), _ChangingPluginV2()}))

    def factory(plugin: Plugin, context: object) -> Plugin:
        if plugin.name == "changing_plugin":
            return _ChangingPluginV2()
        return plugin

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        discovery_factory=discover,
        replacement_factory=factory,
    )

    trigger = tmp_path / "some_module.py"
    trigger.write_text("# change", encoding="utf-8")
    await controller.handle_change(trigger)

    assert replaced == ["changing_plugin"], f"Unexpected replacements: {replaced}"

    plugins_by_name = {p.name: p for p in manager.get_plugins()}
    assert id(plugins_by_name["stable_plugin"]) == id(stable)
    assert plugins_by_name["changing_plugin"].version == "v2"

    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_zero_replacements_when_nothing_changed(tmp_path: Path) -> None:
    """If discovery returns same classes, zero replacements occur."""
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)

    stable = _StablePlugin()
    await manager.enable_plugin(stable)
    stable_id = id(stable)

    replace_count = 0
    original_replace = manager.replace_plugin

    async def counted_replace(plugin, replacement):
        nonlocal replace_count
        replace_count += 1
        return await original_replace(plugin, replacement)

    manager.replace_plugin = counted_replace  # type: ignore

    def discover(config: object) -> PluginRegistry:
        return PluginRegistry(plugins=frozenset({_StablePlugin()}))

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        discovery_factory=discover,
        replacement_factory=lambda p, c: _StablePlugin(),
    )

    trigger = tmp_path / "some_module.py"
    trigger.write_text("# change", encoding="utf-8")
    await controller.handle_change(trigger)

    assert replace_count == 0, f"Expected 0 replacements, got {replace_count}"
    assert id(stable) == stable_id

    await controller.close()
    await manager.close()
