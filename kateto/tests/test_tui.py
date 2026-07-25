from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static, Switch, TabPane, TabbedContent, Tree

from kateto.core.event import (
    AudioInputStatus,
    AudioInputStatusData,
    AudioOutput,
    AudioOutputStatus,
    AudioOutputStatusData,
    GenerateData,
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
from kateto.plugins.system.tui import KatetoApp, TuiEventData, _FixtureRuntime
from kateto.plugins.system.tui_runtime import TuiPluginConfiguration


class _FixturePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__("fixture_plugin")


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


@pytest.mark.asyncio
async def test_fixture_runtime_wires_responses_and_workflow_catalog(tmp_path: Path) -> None:
    # Given: a fresh fixture configuration directory.
    runtime = _FixtureRuntime(tmp_path)

    # When: the deterministic runtime starts and receives a prompt.
    await runtime.start()
    try:
        await runtime.manager.emit("generate", GenerateData(prompt="show the project status"), source="tui")
        await runtime.manager.wait_for_idle()

        # Then: real event subscribers, generated text, and workflow definitions are visible.
        event_names = {event.name for event in runtime.manager.get_events()}
        assert {"workflow_run", "workflow_phase_start", "generate", "text_chunk"}.issubset(event_names)
        assert runtime.workflow_catalog.discover(voice="jane")
        assert any(
            isinstance(event.data, TextChunk) and event.data.text
            for event in runtime.manager.get_events()
        )
        responses = [
            event.data.text
            for event in runtime.manager.get_events()
            if isinstance(event.data, TextChunk)
        ]
        assert any("coordinate" in response.lower() for response in responses)
        assert any("delivery" in response.lower() for response in responses)
        assert any("agile" in response.lower() for response in responses)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_fixture_tui_shows_workflow_tree_and_voice_responses(tmp_path: Path) -> None:
    # Given: the fixture TUI is connected to its deterministic runtime.
    runtime = _FixtureRuntime(tmp_path)
    app = KatetoApp(runtime=runtime, fixture=True, config_dir=tmp_path)

    # When: the runtime finishes its startup demonstration.
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.2)
        await runtime.manager.wait_for_idle()
        workflow_tree = app.query_one("#workflow-tree", Tree)
        app.query_one("#workspace", TabbedContent).active = "conversation-tab"
        await pilot.pause()

        # Then: the workflow catalog and generated voice text are visible in the TUI.
        assert any(str(node.label) == "project-initiation" for node in workflow_tree.root.children)
        conversation = "\n".join(str(child.render()) for child in app.query_one("#conversation-messages").children)
        assert "fixture response" in conversation


@pytest.mark.asyncio
async def test_tui_escapes_markup_in_conversation_content(tmp_path: Path) -> None:
    # Given: a mounted TUI conversation surface.
    manager = PluginManager()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(manager=manager, runtime_plugins=(engine,), workflow_engine=engine)
    app = KatetoApp(runtime=runtime)

    # When: a response contains markup-like model text.
    async with app.run_test() as pilot:
        await pilot.pause()
        app._add_chat_message("agent", "Jane", "'All stakeholders' [phase]")
        await pilot.pause()

        # Then: the conversation renders the text without a markup exception.
        rendered = str(app.query_one("#conversation-messages").children[-1].render())
        assert "All stakeholders" in rendered


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
async def test_tui_uses_bounded_manager_history(tmp_path: Path) -> None:
    # Given: a manager with a bounded history.
    manager = PluginManager(event_limit=2)
    plugin = _FixturePlugin()
    engine = WorkflowEngine(config_dir=tmp_path)
    runtime = _RuntimeOwnerLike(
        manager=manager,
        runtime_plugins=(plugin, engine),
        workflow_engine=engine,
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
        assert [pane.id for pane in panes] == ["events-tab", "conversation-tab", "plugins-tab", "voices-tab", "workflows-tab", "mcps-tab"]
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
