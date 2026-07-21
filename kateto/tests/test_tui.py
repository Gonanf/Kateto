from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from pathlib import Path
import sys

import pytest
from watchdog.events import FileCreatedEvent, FileModifiedEvent
from textual.widgets import Button, Input, Static, Switch, TabPane, TabbedContent

from kateto.core.hot_reload import HotReloadController, ReloadContext, _ReloadHandler
from kateto.core.event import (
    AudioInputStatus,
    AudioInputStatusData,
    AudioOutput,
    AudioOutputStatus,
    AudioOutputStatusData,
    PluginErrorData,
    VoiceIdleData,
    VoiceStatus,
    VoiceStatusData,
    TextChunk,
    WorkflowRunData,
)
from kateto.core.plugin import Plugin
from kateto.core.manager import PluginManager
from kateto.core.workflow_engine import WorkflowEngine
from kateto.plugins.system.tui import KatetoApp, TuiEventData
from kateto.plugins.system.tui_runtime import TuiPluginConfiguration


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


@dataclass
class _McpRuntime:
    server_name: str
    voice_name: str
    pending_wait_count: int = 0


class _RuntimeOwnerLike:
    def __init__(
        self,
        *,
        manager: PluginManager,
        runtime_plugins: tuple[Plugin, ...],
        workflow_engine: WorkflowEngine,
        mcp_servers: tuple[_McpRuntime, ...] = (),
        workflow_voices: tuple[str, ...] = (),
        plugin_configurations: tuple[TuiPluginConfiguration, ...] = (),
    ) -> None:
        self.manager = manager
        self.runtime_plugins = runtime_plugins
        self.workflow_engine = workflow_engine
        self.workflow_catalog = workflow_engine.catalog
        self.mcp_servers = mcp_servers
        self.workflow_voices = workflow_voices
        self.hot_reload_controller = None
        self.is_started = False
        self._plugin_configurations = {item.plugin: item for item in plugin_configurations}

    @property
    def plugin_configurations(self) -> tuple[TuiPluginConfiguration, ...]:
        return tuple(self._plugin_configurations.values())

    def plugin_configuration(self, name: str) -> TuiPluginConfiguration | None:
        return self._plugin_configurations.get(name)

    def voice_enabled(self, name: str) -> bool:
        return True

    async def configure_plugin(self, name: str, configuration: TuiPluginConfiguration) -> None:
        self._plugin_configurations[name] = configuration

    async def start(self) -> None:
        for plugin in self.runtime_plugins:
            await self.manager.enable_plugin(plugin)
        await self.manager.emit(
            "tui_event",
            TuiEventData(message="runtime ready"),
            source="runtime",
        )
        await self.manager.emit(
            "workflow_run",
            WorkflowRunData(workflow="daily", voice="Conquest"),
            source="runtime",
        )
        self.is_started = True

    async def stop(self) -> None:
        await self.manager.close()
        self.is_started = False


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
async def test_tui_renders_live_runtime_state_and_controls(tmp_path: Path) -> None:
    # Given: a runtime owner with a manager, workflow engine, catalog, and MCP server.
    workflow_path = tmp_path / "workflows" / "daily" / "workflow.py"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(
        "name = 'daily'\n"
        "description = 'runtime workflow'\n"
        "phases = [{'id': 'start', 'name': 'Start', 'instructions': ['work']}]\n",
        encoding="utf-8",
    )
    manager = PluginManager()
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(plugin, engine),
        workflow_engine=engine,
        mcp_servers=(_McpRuntime("backlog", "Conquest"),),
        workflow_voices=("Conquest", "Jane"),
    )

    # When: the Textual app is driven through its real test surface.
    app = KatetoApp(runtime=runtime)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app.query_one("#workspace", TabbedContent).active = "plugins-tab"
        await pilot.pause()
        # ponytail: Switch toggles plugin via on_switch_changed → _set_plugin
        fixture_switch = app.query_one("#switch-fixture_plugin", Switch)
        fixture_switch.value = False
        await pilot.pause(0.1)
        fixture_switch.value = True
        await pilot.pause(0.1)

        # Then: plugins are visible with switch, runtime events are received.
        assert app.runtime.is_started
        assert "fixture_plugin" in app.plugin_text
        assert "backlog" in app._mcp_state()
        assert "runtime ready" in app.event_text
        assert plugin.enabled

    assert not runtime.is_started


@pytest.mark.asyncio
async def test_tui_keeps_plugin_switch_visible_in_narrow_panel(tmp_path: Path) -> None:
    # Given: a plugin panel rendered at a narrow terminal width.
    manager = PluginManager()
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(plugin, engine),
        workflow_engine=engine,
    )
    app = KatetoApp(runtime=runtime)

    # When: the plugins tab is rendered in a narrow terminal.
    async with app.run_test(size=(30, 24)) as pilot:
        app.query_one("#workspace", TabbedContent).active = "plugins-tab"
        await pilot.pause()
        row = app.query_one(".plugin-row")
        selector = app.query_one("#select-fixture_plugin", Static)
        switch = app.query_one("#switch-fixture_plugin", Switch)

        # Then: the real Switch, not a Button styled as one, remains visibly contained.
        assert not isinstance(selector, Switch)
        assert switch.region.width >= 10
        assert switch.region.x >= row.region.x
        assert switch.region.right <= row.region.right
        assert selector.region.width > 0

        # Then: the native switch remains interactive at the narrow width.
        initial_value = switch.value
        switch.toggle()
        await pilot.pause(0.1)
        assert switch.value is not initial_value

    assert not runtime.is_started


@pytest.mark.asyncio
async def test_tui_uses_bounded_manager_history_and_applies_audio_configuration(tmp_path: Path) -> None:
    # Given: a manager with a bounded history and typed device configuration controls.
    manager = PluginManager(event_limit=2)
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(plugin, engine),
        workflow_engine=engine,
        plugin_configurations=(TuiPluginConfiguration(plugin="audio_input_mic", microphone="old"),),
    )
    app = KatetoApp(runtime=runtime)

    async with app.run_test() as pilot:
        app.query_one("#workspace", TabbedContent).active = "plugins-tab"
        await pilot.pause()
        await manager.emit("tui_event", TuiEventData(message="old"), source="fixture_plugin")
        await manager.emit("tui_event", TuiEventData(message="middle"), source="fixture_plugin")
        await manager.emit("tui_event", TuiEventData(message="new"), source="fixture_plugin")
        await pilot.click("#select-fixture_plugin")
        await pilot.pause()
        assert "old" not in app._history_text()
        assert "new" in app._history_text()

        app.query_one("#microphone-audio_input_mic", Input).value = "configured-mic"
        app.query_one("#apply-config-audio_input_mic", Button).press()
        await pilot.pause()
        configured = runtime.plugin_configuration("audio_input_mic")
        assert configured is not None
        assert configured.microphone == "configured-mic"
        assert any(str(notification).startswith("CONFIGURED audio_input_mic") for notification in app._notifications)

    assert not runtime.is_started


@pytest.mark.asyncio
async def test_tui_event_stream_keeps_text_and_audio_output_events(tmp_path: Path) -> None:
    # Given: a TUI connected to the runtime event observer.
    manager = PluginManager(event_limit=4)
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(manager=manager, runtime_plugins=(plugin, engine), workflow_engine=engine)
    app = KatetoApp(runtime=runtime)

    async with app.run_test() as pilot:
        # When: text and audio output events are sent through the manager.
        await manager.emit("text_chunk", TextChunk(text="visible text", sequence=0), source="fixture_plugin")
        await manager.emit("audio_output", AudioOutput(samples=b"pcm", sample_rate=16_000, channels=1), source="fixture_plugin")
        await pilot.pause()

        # Then: both event types remain visible in the TUI stream.
        assert "visible text" in app.event_text
        assert "audio_output" in app.event_text

    assert not runtime.is_started


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
    engine = WorkflowEngine(config_dir=Path.cwd())
    runtime = _RuntimeOwnerLike(manager=manager, runtime_plugins=(), workflow_engine=engine)
    app = KatetoApp(runtime=runtime, fixture=True)
    async with app.run_test() as pilot:
        # When: malformed workflow feedback is published as an error event.
        await manager.emit("tui_event", TuiEventData(message="reload error: malformed workflow"), source="watcher")
        await pilot.pause(0.1)

        # Then: the app remains mounted and the error is visible.
        assert app.is_running
        assert "malformed workflow" in app.event_text
    assert not runtime.is_started


@pytest.mark.asyncio
async def test_tui_workspace_tabs_status_history_and_json_composer(tmp_path: Path) -> None:
    # Given: a live runtime surface with a selectable plugin and voice.
    manager = PluginManager()
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(plugin, engine),
        workflow_engine=engine,
        workflow_voices=("Conquest",),
    )
    app = KatetoApp(runtime=runtime)

    async with app.run_test() as pilot:
        await pilot.pause()

        # When: the user observes tabs, a voice event, plugin selection, and composer states.
        workspace = app.query_one("#workspace", TabbedContent)
        panes = list(workspace.query(TabPane))
        assert [pane.id for pane in panes] == ["events-tab", "plugins-tab", "voices-tab", "workflows-tab", "mcps-tab"]
        assert app.query_one("#composer").parent is app.query_one("#events-tab", TabPane)
        assert app.query_one("#plugins-tab")
        assert app.query_one("#voices-tab")
        assert app.query_one("#workflows-tab")
        assert app.query_one("#mcps-tab")
        workspace.active = "plugins-tab"
        await pilot.pause()
        await manager.emit("voice_idle", VoiceIdleData(voice="Conquest"), source="Conquest")
        await pilot.click("#select-fixture_plugin")
        await manager.emit("tui_event", TuiEventData(message="plugin sent"), source="fixture_plugin")
        await pilot.pause()
        assert "Conquest · idle" in app._voice_text()
        assert "SENT" in app._history_text()

        workspace.active = "events-tab"
        await pilot.pause()
        composer = app.query_one("#composer-input", Input)
        composer.value = "/tui_event"
        app.query_one("#send-event", Button).press()
        await pilot.pause(0.1)
        composer.value = '{"message":"json payload"}'
        app.query_one("#send-event", Button).press()
        await pilot.pause(0.1)

        # Then: strict JSON emits only after selection, invalid JSON becomes a notification,
        # and Enter in the text box never emits an event.
        assert "json payload" in app.event_text
        before_enter = len(manager.get_events())
        composer.value = "ordinary enter"
        await pilot.press("enter")
        await pilot.pause()
        assert len(manager.get_events()) == before_enter
        composer.value = "/tui_event"
        app.query_one("#send-event", Button).press()
        await pilot.pause(0.1)
        composer.value = '{"message":3}'
        app.query_one("#send-event", Button).press()
        await pilot.pause(0.1)
        assert any("invalid JSON" in str(notification) for notification in app._notifications)

        await manager.emit("error", PluginErrorData(plugin="fixture_plugin", event_name="tui_event", error_type="RuntimeError", message="boom"), source="fixture_plugin")
        await pilot.pause()
        assert any("ERROR [fixture_plugin]: boom" in str(notification) for notification in app._notifications)

    assert not runtime.is_started


@pytest.mark.asyncio
async def test_tui_maps_typed_voice_and_audio_status_events(tmp_path: Path) -> None:
    # Given: a live TUI with one voice and input/output audio plugins.
    manager = PluginManager()
    input_plugin = _FixturePlugin()
    input_plugin.name = "audio_input_mic"
    output_plugin = _FixturePlugin()
    output_plugin.name = "audio_output_player"
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(input_plugin, output_plugin, engine),
        workflow_engine=engine,
        workflow_voices=("Conquest",),
    )
    app = KatetoApp(runtime=runtime)

    async with app.run_test() as pilot:
        await pilot.pause()

        # When: observed typed lifecycle events transition voice and audio state.
        await manager.emit("voice_status", VoiceStatusData(voice="Conquest", status=VoiceStatus.WAITING), source="Conquest")
        await manager.emit("voice_status", VoiceStatusData(voice="Conquest", status=VoiceStatus.THINKING), source="Conquest")
        await manager.emit("voice_status", VoiceStatusData(voice="Conquest", status=VoiceStatus.TALKING), source="Conquest")
        await manager.emit("audio_input_status", AudioInputStatusData(status=AudioInputStatus.RECORDING), source="audio_input_mic/mic")
        await manager.emit("audio_output_status", AudioOutputStatusData(status=AudioOutputStatus.PLAYING), source="audio_output_player")
        await pilot.pause()

        # Then: each typed event's payload is the displayed status.
        assert "Conquest · talking" in app._voice_text()
        assert "ON · recording" in next(line for line in app.plugin_text.splitlines() if line.startswith("audio_input_mic"))
        assert "ON · playing" in next(line for line in app.plugin_text.splitlines() if line.startswith("audio_output_player"))

        await manager.emit("voice_status", VoiceStatusData(voice="Conquest", status=VoiceStatus.IDLE), source="Conquest")
        await manager.emit("audio_input_status", AudioInputStatusData(status=AudioInputStatus.IDLE), source="audio_input_mic/mic")
        await manager.emit("audio_output_status", AudioOutputStatusData(status=AudioOutputStatus.IDLE), source="audio_output_player")
        await pilot.pause()
        assert "Conquest · idle" in app._voice_text()
        assert "ON · idle" in next(line for line in app.plugin_text.splitlines() if line.startswith("audio_input_mic"))
        assert "ON · idle" in next(line for line in app.plugin_text.splitlines() if line.startswith("audio_output_player"))

    assert not runtime.is_started
