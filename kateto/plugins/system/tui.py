from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from pathlib import Path
from typing import assert_never

from pydantic import BaseModel, Field, ValidationError
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static, TabbedContent, TabPane

from kateto.core.event import (
    AudioInputStatusData,
    AudioOutputStatusData,
    EventEnvelope,
    EventModel,
    PluginErrorData,
    VoiceStatusData,
)
from kateto.core.hot_reload import HotReloadController, ReloadContext, ReplacementFactory
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowDefinition, WorkflowDefinitionError, WorkflowPhaseStatus, WorkflowStatus
from kateto.core.workflow_engine import WorkflowSnapshot
from kateto.plugins.system.tui_runtime import TuiConfigurationRuntime, TuiPluginConfiguration, TuiRuntime


class TuiEventData(EventModel):
    message: str = Field(min_length=1)


class _FixturePlugin(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name, capabilities=("fixture",))


class _FixtureRuntime:
    def __init__(self, config_dir: Path) -> None:
        from kateto.core.workflow_engine import WorkflowEngine

        self.manager = PluginManager()
        self.runtime_plugins = tuple(_FixturePlugin(name) for name in ("voice_jane", "voice_doktor", "voice_conquest", "workflow_engine"))
        self._workflow_engine = WorkflowEngine(config_dir=config_dir)
        self.mcp_servers = ()
        self.workflow_voices = ("Jane", "Doktor", "Conquest")
        self.hot_reload_controller = None
        self.is_started = False
        self.plugin_configurations = ()

    @property
    def workflow_catalog(self):
        return self._workflow_engine.catalog

    @property
    def workflow_engine(self):
        return self._workflow_engine

    async def start(self) -> None:
        for plugin in self.runtime_plugins:
            await self.manager.enable_plugin(plugin)
        await self.manager.emit("tui_event", TuiEventData(message="fixture dashboard ready"), source="fixture")
        self.is_started = True

    async def stop(self) -> None:
        await self.manager.close()
        self.is_started = False


class KatetoApp(App[None]):
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #workspace { height: 1fr; min-height: 0; }
    TabbedContent { height: 1fr; }
    .tab-body { padding: 1 2; height: 1fr; overflow-y: auto; }
    .section-title { color: $accent; text-style: bold; margin-bottom: 1; }
    .plugin-row { height: 3; width: 1fr; }
    .plugin-name { width: 22; min-width: 12; content-align: left middle; }
    .plugin-row Button { width: 10; border: none; background: transparent; }
    #plugin-history { height: 1fr; border: round $secondary; padding: 1; overflow-y: auto; }
    #notifications { height: 5; border: round $error; padding: 0 1; color: $error; overflow-y: auto; }
    #composer { dock: bottom; height: 5; padding: 0 1; }
    #composer-input { width: 1fr; }
    #send-event { width: 16; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]

    def __init__(self, *, runtime: TuiRuntime, fixture: bool = False, config_dir: Path | None = None, replacement_factory: ReplacementFactory | None = None) -> None:
        super().__init__()
        self.runtime = runtime
        self.manager = runtime.manager
        self.fixture = fixture
        self.config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
        self.replacement_factory = replacement_factory or (self._fixture_replacement_factory if fixture else None)
        self._events: list[str] = []
        self._notifications: list[str] = []
        self._voice_status: dict[str, str] = {voice: "idle" for voice in runtime.workflow_voices}
        self._audio_status: dict[str, str] = {}
        self._selected_plugin: str | None = None
        self._selected_event: str | None = None
        self._controller: HotReloadController | None = None
        self._stop_runtime_started = False
        self.manager.register_event("tui_event", TuiEventData)
        self.manager.add_event_observer(self._observe_event)

    @property
    def plugin_text(self) -> str:
        return self._plugin_state()

    @property
    def mcp_text(self) -> str:
        return self._mcp_state()

    @property
    def workflow_text(self) -> str:
        return self._format_workflows()

    @property
    def runtime_text(self) -> str:
        return f"RUNTIME: {'RUNNING' if self.runtime.is_started else 'STOPPED'}"

    @property
    def event_text(self) -> str:
        return "\n".join(self._events)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="workspace"):
            with TabPane("Events", id="events-tab"):
                yield Static("EVENT STREAM", classes="section-title")
                yield Static(id="event-state")
                with Vertical(id="composer"):
                    yield Label("Composer: ordinary text → tui_event · /event_name → strict JSON payload", id="composer-mode")
                    with Horizontal():
                        yield Input(placeholder="message or /registered_event", id="composer-input")
                        yield Button("Emit", id="send-event", variant="primary")
                    yield Static(id="notifications")
            with TabPane("Plugins", id="plugins-tab"):
                yield Static("PLUGINS", classes="section-title")
                yield Static(id="plugin-state")
                yield Static("Select a plugin to inspect sent / received events", classes="section-title")
                yield Static(id="plugin-history")
                for plugin in self._available_plugins():
                    yield self._plugin_controls(plugin)[0]
                yield Static(id="plugin-config")
                for configuration in self._configuration_items():
                    yield Label(f"{configuration.plugin} device configuration", classes="section-title")
                    yield Input(value=configuration.microphone or "", placeholder="microphone device", id=f"microphone-{configuration.plugin}")
                    yield Input(value=configuration.speaker or "", placeholder="speaker device", id=f"speaker-{configuration.plugin}")
                    yield Button("Apply device configuration", id=f"apply-config-{configuration.plugin}")
            with TabPane("Voices", id="voices-tab"):
                yield Static("RUNTIME VOICES", classes="section-title")
                yield Static(id="voice-state")
            with TabPane("Global Workflows", id="workflows-tab"):
                yield Static("WORKFLOW TREE", classes="section-title")
                yield Static(id="workflow-state")
            with TabPane("MCPs", id="mcps-tab"):
                yield Static("MCP SERVERS", classes="section-title")
                yield Static(id="mcp-state")
        yield Footer()

    def on_mount(self) -> None:
        for event in self.manager.get_events():
            self._record_event(event)
        self._refresh_view()
        self.run_worker(self._start_runtime, exclusive=True)

    async def _start_runtime(self) -> None:
        await self.runtime.start()
        if self.fixture and self.runtime.hot_reload_controller is None and self.replacement_factory is not None:
            self._controller = HotReloadController(manager=self.manager, watched_root=self.config_dir, loop=asyncio.get_running_loop(), replacement_factory=self.replacement_factory)
            await self._controller.start()
        self._refresh_view()

    async def on_unmount(self) -> None:
        self.manager.remove_event_observer(self._observe_event)
        await self._stop_runtime()

    async def _stop_runtime(self) -> None:
        if self._stop_runtime_started:
            return
        self._stop_runtime_started = True
        if self._controller is not None:
            await self._controller.close()
            self._controller = None
        await self.runtime.stop()

    async def action_quit(self) -> None:
        await self._stop_runtime()
        self.exit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "send-event":
            self.query_one("#composer-input", Input).focus()
            self.run_worker(self._submit_composer(), exclusive=False)
            return
        if button_id.startswith("select-"):
            self._selected_plugin = button_id.removeprefix("select-")
            self._refresh_view()
            return
        if button_id.startswith("apply-config-"):
            self.run_worker(self._configure_plugin(button_id.removeprefix("apply-config-")), exclusive=False)
            return
        prefix, _, name = button_id.partition("-")
        if prefix in {"enable", "disable"} and name:
            self.run_worker(self._set_plugin(name, prefix == "enable"), exclusive=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()

    async def _submit_composer(self) -> None:
        input_widget = self.query_one("#composer-input", Input)
        value = input_widget.value.strip()
        if not value:
            return
        if value.startswith("/"):
            name = value[1:].strip()
            contract = next((item.contract for item in self.manager.get_event_registrations() if item.name == name), None)
            if contract is None:
                self._notify(f"ERROR: unknown event /{name}")
            else:
                self._selected_event = name
                self.query_one("#composer-mode", Label).update(f"Payload for /{name}: strict JSON for {contract.__name__}")
                input_widget.value = ""
            self._refresh_view()
            return
        if self._selected_event is None:
            await self._emit_manual(value)
            input_widget.value = ""
            return
        registration = next(item for item in self.manager.get_event_registrations() if item.name == self._selected_event)
        try:
            payload = registration.contract.model_validate_json(value)
        except ValidationError as error:
            self._notify(f"ERROR: invalid JSON for /{self._selected_event}: {error.errors()[0]['msg']}")
            self._refresh_view()
            return
        await self.manager.emit(self._selected_event, payload, source="tui")
        self._selected_event = None
        input_widget.value = ""
        self.query_one("#composer-mode", Label).update("Composer: ordinary text → tui_event · /event_name → strict JSON payload")

    async def _emit_manual(self, message: str) -> None:
        await self.manager.emit("tui_event", TuiEventData(message=message), source="tui")

    async def _set_plugin(self, name: str, enabled: bool) -> None:
        if enabled:
            plugin = next((item for item in self._available_plugins() if item.name == name), None)
            if plugin is not None:
                await self.manager.enable_plugin(plugin)
        else:
            await self.manager.disable_plugin(name)
        self._refresh_view()

    async def _configure_plugin(self, name: str) -> None:
        if not isinstance(self.runtime, TuiConfigurationRuntime):
            return
        current = self.runtime.plugin_configuration(name)
        if current is None:
            self._notify(f"ERROR: unknown plugin configuration {name}")
            self._refresh_view()
            return
        microphone = self.query_one(f"#microphone-{name}", Input).value.strip() or None
        speaker = self.query_one(f"#speaker-{name}", Input).value.strip() or None
        await self.runtime.configure_plugin(
            name,
            TuiPluginConfiguration(
                plugin=name,
                microphone=microphone,
                speaker=speaker,
                values=current.values,
            ),
        )
        self._notify(f"CONFIGURED {name}: microphone={microphone or 'default'}, speaker={speaker or 'default'}")
        self._refresh_view()

    @staticmethod
    def _fixture_replacement_factory(plugin: Plugin, _context: ReloadContext) -> Plugin:
        return _FixturePlugin(plugin.name)

    def _observe_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        self._record_event(envelope)
        self._refresh_view_after_event()

    def _record_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        formatted = self._format_event(envelope)
        self._events.append(formatted)
        if isinstance(envelope.data, PluginErrorData):
            self._notify(f"ERROR [{envelope.data.plugin}]: {envelope.data.message}")
        self._update_voice_status(envelope)
        self._update_audio_status(envelope)

    def _refresh_view_after_event(self) -> None:
        if self.is_mounted:
            self.call_after_refresh(self._refresh_view)

    def _refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#plugin-state", Static).update(self._plugin_state())
        self.query_one("#plugin-history", Static).update(self._history_text())
        self.query_one("#plugin-config", Static).update(self._configuration_text())
        self.query_one("#voice-state", Static).update(self._voice_text())
        self.query_one("#workflow-state", Static).update(self._format_workflows())
        self.query_one("#mcp-state", Static).update(self._mcp_state())
        self.query_one("#event-state", Static).update(self.event_text or "waiting for events")
        self.query_one("#notifications", Static).update("\n".join(self._notifications[-4:]) or "notifications: none")

    def _notify(self, message: str) -> None:
        self._notifications.append(message)

    def _available_plugins(self) -> tuple[Plugin, ...]:
        plugins: dict[str, Plugin] = {plugin.name: plugin for plugin in self.runtime.runtime_plugins}
        plugins.update({plugin.name: plugin for plugin in self.manager.get_plugins()})
        return tuple(plugins.values())

    def _plugin_state(self) -> str:
        return "\n".join(
            f"{plugin.name:<24} {'ON' if plugin.enabled else 'OFF'}"
            f"{f' · {self._audio_status[plugin.name]}' if plugin.name in self._audio_status else ''}"
            for plugin in self._available_plugins()
        ) or "no plugins"

    def _history_text(self) -> str:
        name = self._selected_plugin
        if name is None:
            return "no plugin selected"
        history = self.manager.get_plugin_event_history(name)
        sent = (f"SENT  {self._format_event(event)}" for event in history.sent)
        received = (f"RECV  {self._format_event(event)}" for event in history.received)
        return f"{name}\n" + "\n".join((*sent, *received))

    def _configuration_text(self) -> str:
        configurations = self._configuration_items()
        if not configurations:
            return "configuration: runtime has no editable plugin settings"
        return "CONFIGURATION\n" + "\n".join(self._format_configuration(item) for item in configurations)

    def _configuration_items(self) -> tuple[TuiPluginConfiguration, ...]:
        if not isinstance(self.runtime, TuiConfigurationRuntime):
            return ()
        return self.runtime.plugin_configurations

    @staticmethod
    def _format_configuration(configuration: TuiPluginConfiguration) -> str:
        audio = ", ".join(value for value in (f"microphone={configuration.microphone}" if configuration.microphone else "", f"speaker={configuration.speaker}" if configuration.speaker else "") if value)
        return f"{configuration.plugin}: {audio or 'configured'}"

    def _voice_text(self) -> str:
        return "\n".join(f"{voice} · {self._voice_status.get(voice, 'idle')}" for voice in self.runtime.workflow_voices) or "no voices"

    def _update_voice_status(self, envelope: EventEnvelope[BaseModel]) -> None:
        if isinstance(envelope.data, VoiceStatusData) and envelope.data.voice in self.runtime.workflow_voices:
            self._voice_status[envelope.data.voice] = envelope.data.status.value

    def _update_audio_status(self, envelope: EventEnvelope[BaseModel]) -> None:
        status_data = envelope.data
        if isinstance(status_data, AudioInputStatusData | AudioOutputStatusData):
            plugin = envelope.source.split("/", maxsplit=1)[0]
            self._audio_status[plugin] = status_data.status.value

    def _format_workflows(self) -> str:
        groups: list[str] = []
        for voice in self.runtime.workflow_voices:
            try:
                definitions = self.runtime.workflow_catalog.discover(voice=voice)
            except WorkflowDefinitionError as error:
                groups.append(f"{voice} · — · ⚪ INACTIVE\n  └ Catalog error: {error}")
                continue
            if definitions:
                groups.extend(self._format_workflow(definition, voice) for definition in definitions)
            else:
                groups.append(f"{voice} · — · ⚪ INACTIVE")
        return "\n\n".join(groups) or "no workflows"

    def _format_workflow(self, definition: WorkflowDefinition, voice: str) -> str:
        snapshot = self.runtime.workflow_engine.snapshot(workflow=definition.name, voice=voice)
        if snapshot is None:
            return f"{voice} · {definition.name} · ⚪ INACTIVE"
        phase_index, phase = next((index, phase) for index, phase in enumerate(definition.phases) if phase.id.casefold() == snapshot.phase_id.casefold())
        icon = self._status_icon(snapshot)
        completed = snapshot.phase_status is WorkflowPhaseStatus.DONE
        instructions = len(phase.instructions)
        checkpoints = len(phase.checkpoints)
        return "\n".join((f"{voice} · {definition.name} · {icon} {snapshot.status.value.upper()}", f"  ├ Fase activa: {phase.name} ({phase_index + 1}/{len(definition.phases)})", f"  ├ Tarea actual: {phase.instructions[0] if phase.instructions else '—'}", f"  ├ Progreso: {instructions if completed else 0}/{instructions} instrucciones", f"  └ Checkpoints: {checkpoints if completed else 0}/{checkpoints} ✓"))

    @staticmethod
    def _status_icon(snapshot: WorkflowSnapshot) -> str:
        match snapshot.status:
            case WorkflowStatus.RUNNING:
                return "🟡"
            case WorkflowStatus.PAUSED:
                return "🟠"
            case WorkflowStatus.STOPPED:
                return "🔴"
            case WorkflowStatus.COMPLETED:
                return "🟢"
            case unreachable:
                assert_never(unreachable)

    def _mcp_state(self) -> str:
        runtime_status = "READY" if self.runtime.is_started else "STOPPED"
        return "\n".join(f"{server.server_name} / {server.voice_name}: {runtime_status} · waits={server.pending_wait_count}" for server in self.runtime.mcp_servers) or "no MCP servers"

    @staticmethod
    def _format_event(envelope: EventEnvelope[BaseModel]) -> str:
        data = envelope.data
        if isinstance(data, TuiEventData | PluginErrorData):
            message = data.message
        else:
            message = type(data).__name__
        return f"{envelope.name:<22} {envelope.source:<16} {message}"

    def _plugin_controls(self, plugin: Plugin) -> tuple[Horizontal, ...]:
        return (Horizontal(Button(plugin.name, id=f"select-{plugin.name}", classes="plugin-name"), Button("On", id=f"enable-{plugin.name}"), Button("Off", id=f"disable-{plugin.name}"), classes="plugin-row"),)


def run_tui(*, fixture: bool = False, config_dir: Path | None = None) -> None:
    resolved_config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
    if fixture:
        runtime: TuiRuntime = _FixtureRuntime(resolved_config_dir)
    else:
        from kateto.core.config import load_config
        from kateto.run_mode import build_runtime_owner

        runtime = build_runtime_owner(load_config(config_dir=resolved_config_dir))
    KatetoApp(runtime=runtime, fixture=fixture, config_dir=resolved_config_dir).run()
