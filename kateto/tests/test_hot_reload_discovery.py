from __future__ import annotations

from pathlib import Path

import pytest

from pydantic import BaseModel

from kateto.core.discovery import PluginRegistry
from kateto.core.hot_reload import HotReloadController
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class _TestEventData(BaseModel):
    payload: str = "ping"


class _DiscoveredPlugin(Plugin):
    def __init__(self, version: str = "") -> None:
        super().__init__("discovered_plugin")
        self.version = version
        self.handled_events: list[str] = []

    async def on_test_event(self, data: object) -> None:
        self.handled_events.append("test_event")


class _ReplaceablePlugin(Plugin):
    def __init__(self, name: str = "replaceable_plugin", marker: str = "") -> None:
        super().__init__(name, streaming=True)
        self.marker = marker
        self.handled_events: list[str] = []

    async def on_test_event(self, data: object) -> None:
        self.handled_events.append(f"test_event:{self.marker}")


def _write_config(root: Path) -> None:
    _ = (root / "config.toml").write_text(
        "[kateto]\n\n[cli]\nallowlist = [\"echo\"]\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_hot_reload_replaces_plugin_via_replacement_factory(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)
    original = _ReplaceablePlugin(marker="original")
    await manager.enable_plugin(original)
    assert original.enabled
    assert original.marker == "original"

    replacement = _ReplaceablePlugin(marker="replacement")
    assert replacement is not original

    def factory(plugin: Plugin, context: object) -> Plugin:
        return replacement

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=factory,
    )
    config_path = tmp_path / "config.toml"
    await controller.handle_change(config_path)

    plugins = {p.name: p for p in manager.get_plugins()}
    assert "replaceable_plugin" in plugins
    assert plugins["replaceable_plugin"] is replacement
    assert replacement.enabled
    assert replacement.marker == "replacement"
    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_preserves_observers_after_replacement(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)
    original = _ReplaceablePlugin(marker="original")
    await manager.enable_plugin(original)

    observed: list[str] = []

    def observer(envelope: object) -> None:
        observed.append("observed")

    manager.add_event_observer(observer)
    await manager.emit("test_event", _TestEventData(), source="test")
    assert len(observed) == 1

    replacement = _ReplaceablePlugin(marker="replacement")

    def factory(plugin: Plugin, context: object) -> Plugin:
        return replacement

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=factory,
    )
    await controller.handle_change(tmp_path / "config.toml")
    observed.clear()
    await manager.emit("test_event", _TestEventData(), source="test")
    assert len(observed) == 1
    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_replaced_plugin_receives_events(tmp_path: Path) -> None:
    _write_config(tmp_path)
    manager = PluginManager()
    manager.register_event("test_event", _TestEventData)
    original = _ReplaceablePlugin(marker="original")
    await manager.enable_plugin(original)

    replacement = _ReplaceablePlugin(marker="replacement")

    def factory(plugin: Plugin, context: object) -> Plugin:
        return replacement

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=factory,
    )
    await controller.handle_change(tmp_path / "config.toml")
    await manager.emit("test_event", _TestEventData(), source="test")
    await manager.wait_for_idle(timeout=2)
    assert len(replacement.handled_events) == 1
    assert replacement.handled_events[0] == "test_event:replacement"
    await controller.close()
    await manager.close()


def test_hot_reload_accepts_repository_plugin_and_voice_roots(tmp_path: Path) -> None:
    # Given: a config root and separate repository source roots.
    config_root = tmp_path / "config"
    plugin_root = tmp_path / "repository" / "kateto" / "plugins"
    voice_root = tmp_path / "repository" / "kateto" / "voices"
    config_root.mkdir(parents=True)
    plugin_root.mkdir(parents=True)
    voice_root.mkdir(parents=True)
    controller = HotReloadController(
        manager=PluginManager(),
        watched_root=config_root,
        source_roots=(plugin_root, voice_root),
    )

    # When: source paths are checked against the controller's watch set.
    plugin_path = plugin_root / "example.py"
    voice_path = voice_root / "example.py"

    # Then: config, plugin, and voice roots are all accepted.
    assert controller._is_watched(config_root / "config.toml")
    assert controller._is_watched(plugin_path)
    assert controller._is_watched(voice_path)
    assert not controller._is_watched(tmp_path / "outside.py")


@pytest.mark.asyncio
async def test_hot_reload_reconciles_created_modified_and_deleted_definitions(tmp_path: Path) -> None:
    # Given: a running manager and a source-root definition whose registry result follows its file.
    _write_config(tmp_path)
    source_root = tmp_path / "repository" / "kateto" / "plugins"
    source_root.mkdir(parents=True)
    source_path = source_root / "discovered.py"
    manager = PluginManager()
    versions = {"created": "v1", "modified": "v2"}

    def discover(config: object) -> PluginRegistry:
        del config
        if not source_path.exists():
            return PluginRegistry(plugins=frozenset())
        version = versions["modified"] if source_path.read_text(encoding="utf-8") == "v2" else versions["created"]
        plugin = _DiscoveredPlugin(version)
        return PluginRegistry(plugins=frozenset({plugin}))

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        source_roots=(source_root,),
        discovery_factory=discover,
    )

    # When: a definition is created, modified, and then deleted.
    source_path.write_text("v1", encoding="utf-8")
    await controller.handle_change(source_path)
    created = manager.get_plugins()[0]
    assert isinstance(created, _DiscoveredPlugin)
    source_path.write_text("v2", encoding="utf-8")
    await controller.handle_change(source_path)
    modified = manager.get_plugins()[0]
    assert isinstance(modified, _DiscoveredPlugin)
    source_path.unlink()
    await controller.handle_change(source_path)

    # Then: each filesystem transition is reflected in active event registrations.
    assert created.version == "v1"
    assert modified.version == "v2"
    assert modified is not created
    assert manager.get_plugins() == (modified,)
    assert not modified.enabled
    assert all(
        "discovered_plugin" not in registration.receivers
        for registration in manager.get_event_registrations()
    )
    await controller.close()
    await manager.close()
