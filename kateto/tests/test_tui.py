from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent

from kateto.core.hot_reload import HotReloadController, ReloadContext, _ReloadHandler
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.plugins.system.tui import KatetoApp, TuiEventData


class _FixturePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("fixture_plugin")


class _ReloadCountingPlugin(Plugin):
    def __init__(self, *, enabled: asyncio.Event | None = None) -> None:
        super().__init__("reload_counting_plugin")
        self.enable_calls = 0
        self.reloaded = asyncio.Event()
        self._enabled = enabled

    async def enable(self) -> None:
        self.enable_calls += 1
        if self._enabled is not None:
            self._enabled.set()
        if self.enable_calls == 2:
            self.reloaded.set()


class _ConfiguredPlugin(Plugin):
    def __init__(self, *, hot_reload: bool) -> None:
        super().__init__("configured_plugin")
        self.hot_reload = hot_reload


def _config_source(*, hot_reload: bool) -> str:
    enabled = "true" if hot_reload else "false"
    return f"[kateto]\nhot_reload = {enabled}\n\n[cli]\nallowlist = [\"echo\"]\n"


def _module_source(*, version: str) -> str:
    return (
        "from kateto.core.plugin import Plugin\n\n"
        "class ReloadablePlugin(Plugin):\n"
        "    def __init__(self, name: str = \"reloadable_plugin\") -> None:\n"
        "        super().__init__(name)\n"
        f"        self.version = {version!r}\n"
    )


@pytest.mark.asyncio
async def test_tui_renders_plugins_and_event_rows_and_controls() -> None:
    # Given: a manager with one controllable fixture plugin and an emitted event.
    manager = PluginManager()
    plugin = _FixturePlugin()
    await manager.enable_plugin(plugin)
    await manager.emit("tui_event", TuiEventData(message="fixture ready"), source="fixture")

    # When: the Textual app is driven through its real test surface.
    app = KatetoApp(manager=manager, fixture=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#disable-fixture_plugin")
        await pilot.click("#enable-fixture_plugin")
        await pilot.pause()

    # Then: the app rendered the state and controls changed the live plugin.
    assert "fixture_plugin" in app.plugin_text
    assert "fixture ready" in app.event_text
    assert plugin.enabled
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_replaces_plugin_and_clears_queued_events(tmp_path: Path) -> None:
    # Given: a running plugin and a watched configuration root.
    (tmp_path / "config.toml").write_text(_config_source(hot_reload=False), encoding="utf-8")
    manager = PluginManager()
    plugin = _FixturePlugin()
    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=lambda _plugin, _context: _FixturePlugin(),
    )
    await manager.enable_plugin(plugin)

    # When: a relevant file change is delivered to the active loop.
    await controller.handle_change(tmp_path / "config.toml")

    # Then: a replacement is enabled and the old queue is empty.
    active = manager.get_plugins()[0]
    assert active is not plugin
    assert active.enabled
    assert plugin.queue.empty()
    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_replaces_plugin_with_changed_config(tmp_path: Path) -> None:
    # Given: an enabled plugin and a valid configuration that will change its setting.
    config_path = tmp_path / "config.toml"
    config_path.write_text(_config_source(hot_reload=False), encoding="utf-8")
    replacements: list[_ConfiguredPlugin] = []

    def replace_plugin(_plugin: Plugin, context: ReloadContext) -> Plugin:
        config = context.config
        assert config is not None
        replacement = _ConfiguredPlugin(hot_reload=config.settings.kateto.hot_reload)
        replacements.append(replacement)
        return replacement

    manager = PluginManager()
    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=replace_plugin,
    )
    original = _ConfiguredPlugin(hot_reload=False)
    await manager.enable_plugin(original)

    # When: the watched config is replaced with a different value.
    config_path.write_text(_config_source(hot_reload=True), encoding="utf-8")
    await controller.handle_change(config_path)

    # Then: the manager owns a distinct plugin constructed from the new parsed config.
    active = manager.get_plugins()[0]
    assert active is replacements[0]
    assert active is not original
    assert replacements[0].hot_reload
    await controller.close()
    await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_replaces_changed_plugin_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: an imported plugin module under the watched root.
    module_name = "reloadable_plugin_fixture"
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(_module_source(version="before"), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    candidate = vars(module)["ReloadablePlugin"]
    assert isinstance(candidate, type)
    assert issubclass(candidate, Plugin)
    manager = PluginManager()

    def replace_plugin(_plugin: Plugin, context: ReloadContext) -> Plugin:
        replacement_type = context.plugin_type
        assert replacement_type is not None
        return replacement_type("reloadable_plugin")

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        replacement_factory=replace_plugin,
    )
    original = candidate("reloadable_plugin")
    await manager.enable_plugin(original)

    try:
        # When: the source module is changed and the watched path is delivered.
        module_path.write_text(_module_source(version="after replacement"), encoding="utf-8")
        await controller.handle_change(module_path)

        # Then: the active plugin is a new object from the reloaded module source.
        active = manager.get_plugins()[0]
        assert active is not original
        assert getattr(active, "version") == "after replacement"
    finally:
        await controller.close()
        await manager.close()
        sys.modules.pop(module_name, None)


@pytest.mark.asyncio
async def test_hot_reload_coalesces_immediate_watchdog_events(tmp_path: Path) -> None:
    # Given: a running plugin and two immediate relevant watchdog file events.
    (tmp_path / "config.toml").write_text(_config_source(hot_reload=False), encoding="utf-8")
    manager = PluginManager()
    plugin = _ReloadCountingPlugin()
    replacement_enabled = asyncio.Event()
    replacements: list[_ReloadCountingPlugin] = []

    def replace_plugin(_plugin: Plugin, _context: ReloadContext) -> Plugin:
        replacement = _ReloadCountingPlugin(enabled=replacement_enabled)
        replacements.append(replacement)
        return replacement

    controller = HotReloadController(
        manager=manager,
        watched_root=tmp_path,
        loop=asyncio.get_running_loop(),
        replacement_factory=replace_plugin,
    )
    await manager.enable_plugin(plugin)
    handler = _ReloadHandler(controller)

    try:
        # When: watchdog delivers the create/modify burst through the thread-safe boundary.
        handler.on_any_event(FileCreatedEvent(str(tmp_path / "config.toml")))
        handler.on_any_event(FileModifiedEvent(str(tmp_path / "config.toml")))
        await asyncio.wait_for(replacement_enabled.wait(), timeout=1)
        await asyncio.sleep(0.2)

        # Then: the initial object is replaced exactly once after the burst.
        assert plugin.enable_calls == 1
        assert len(replacements) == 1
        assert replacements[0].enable_calls == 1
    finally:
        await controller.close()
        await manager.close()


@pytest.mark.asyncio
async def test_hot_reload_close_cancels_active_task_and_blocks_thread_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a reload task that stays blocked after watchdog has scheduled it.
    manager = PluginManager()
    loop = asyncio.get_running_loop()
    controller = HotReloadController(manager=manager, watched_root=tmp_path, loop=loop)
    handler = _ReloadHandler(controller)
    controller._handler = handler
    started = asyncio.Event()
    cancelled = asyncio.Event()
    reload_task: asyncio.Task[None] | None = None

    async def blocked_reload(_path: Path) -> None:
        nonlocal reload_task
        reload_task = asyncio.current_task()
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(controller, "handle_change", blocked_reload)

    try:
        handler._reload(tmp_path / "config.toml")
        await asyncio.wait_for(started.wait(), timeout=1)

        # When: the controller is closed while reload work is still active.
        await controller.close()

        # Then: shutdown owns the task and blocks further watchdog thread callbacks.
        assert cancelled.is_set()
        assert controller._reload_tasks == set()
        bridge_calls: list[None] = []
        original_threadsafe = loop.call_soon_threadsafe

        def record_thread_callback() -> None:
            bridge_calls.append(None)

        monkeypatch.setattr(loop, "call_soon_threadsafe", record_thread_callback)
        handler.on_any_event(FileModifiedEvent(str(tmp_path / "config.toml")))
        monkeypatch.setattr(loop, "call_soon_threadsafe", original_threadsafe)
        assert bridge_calls == []
    finally:
        if reload_task is not None and not reload_task.done():
            reload_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await reload_task
        await controller.close()
        await manager.close()


@pytest.mark.asyncio
async def test_tui_reports_malformed_reload_without_stopping() -> None:
    # Given: a TUI with a reload callback that reports an invalid definition.
    manager = PluginManager()
    app = KatetoApp(manager=manager, fixture=True)
    async with app.run_test() as pilot:
        # When: malformed workflow feedback is published as an error event.
        await manager.emit("tui_event", TuiEventData(message="reload error: malformed workflow"), source="watcher")
        await pilot.pause()

        # Then: the app remains mounted and the error is visible.
        assert app.is_running
        assert "malformed workflow" in app.event_text
    await manager.close()
