from __future__ import annotations

import json
import asyncio  # noqa: ANYIO_OK
from collections import deque
from pathlib import Path
from typing import assert_never

from pydantic import BaseModel, Field, ValidationError
from pydantic.fields import FieldInfo
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, Switch, TabbedContent, TabPane, Tree

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
        self.runtime_plugins = tuple(
            _FixturePlugin(name)
            for name in ("voice_jane", "voice_doktor", "voice_conquest", "workflow_engine")
        )
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
    .section-title { color: $accent; text-style: bold; margin-bottom: 1; }

    /* Events tab */
    #events-body { height: 1fr; margin-bottom: 1; }
    #events-content { height: 100%; }
    #events-stream { width: 1fr; height: 100%; }
    #event-state { height: 1fr; border: solid $secondary; padding: 1; overflow-y: auto; }
    #events-registrations { width: 40%; height: 100%; border: round $secondary; padding: 1; }
    #event-registrations-tree { height: 1fr; overflow-y: auto; min-height: 0; }
    #composer { dock: bottom; height: 5; padding: 0 1; }
    #composer-input { width: 1fr; }
    #send-event { width: 16; }

    /* Plugins tab */
    #plugin-panel { height: 1fr; }
    #plugin-panel-left { width: 40%; height: 1fr; overflow-y: auto; border: round $secondary; padding: 1; }
    #plugin-panel-right { width: 1fr; height: 1fr; border: round $secondary; padding: 1; }
    .plugin-row { height: 3; width: 1fr; align: center middle; }
    .plugin-status { width: 3; content-align: center middle; }
    .plugin-name { width: 24; }
    .plugin-name.selected { background: $accent; color: $surface; }
    Switch { margin: 0 2; }
    #plugin-history { height: auto; max-height: 12; overflow-y: auto; min-height: 0; border-top: solid $secondary; margin-top: 1; padding: 1; }
    #plugin-config-section { height: auto; max-height: 12; overflow-y: auto; border-top: solid $secondary; margin-top: 1; padding: 1; }
    #event-autocomplete { height: auto; max-height: 10; border: solid $secondary; display: none; overflow-y: auto; }

    /* Voices tab */
    #voice-tree { height: 1fr; }

    /* Workflows tab */
    #workflow-tree { height: 1fr; }

    /* MCPs tab */
    #mcp-state { height: 1fr; border: solid $secondary; padding: 1; overflow-y: auto; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]

    def __init__(
        self,
        *,
        runtime: TuiRuntime,
        fixture: bool = False,
        config_dir: Path | None = None,
        replacement_factory: ReplacementFactory | None = None,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.manager = runtime.manager
        self.fixture = fixture
        self.config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
        self.replacement_factory = replacement_factory or (self._fixture_replacement_factory if fixture else None)
        self._events: deque[str] = deque(maxlen=1000)
        self._voice_status: dict[str, str] = {voice: "idle" for voice in runtime.workflow_voices}
        self._audio_status: dict[str, str] = {}
        self._selected_plugin: str | None = None
        self._selected_event: str | None = None
        self._controller: HotReloadController | None = None
        self._stop_runtime_started = False
        self.manager.register_event("tui_event", TuiEventData)
        self.manager.add_event_observer(self._observe_event)

    @property
    def event_text(self) -> str:
        return "\n".join(self._events)

    @property
    def plugin_text(self) -> str:
        lines: list[str] = []
        for plugin in self._available_plugins():
            on_off = "ON" if plugin.enabled else "OFF"
            audio = self._audio_status.get(plugin.name)
            suffix = f" · {audio}" if audio else ""
            lines.append(f"{plugin.name} {on_off}{suffix}")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="workspace"):
            with TabPane("Events", id="events-tab"):
                yield Static("EVENT STREAM", classes="section-title")
                with Vertical(id="events-body"):
                    with Horizontal(id="events-content"):
                        with Vertical(id="events-stream"):
                            yield Static(id="event-state")
                        with Vertical(id="events-registrations"):
                            yield Static("REGISTERED EVENTS", classes="section-title")
                            yield Tree("Events", id="event-registrations-tree")
                yield ListView(id="event-autocomplete")
                with Vertical(id="composer"):
                    yield Label(
                        "Composer: ordinary text → tui_event · /event_name → strict JSON payload",
                        id="composer-mode",
                    )
                    with Horizontal():
                        yield Input(placeholder="message or /registered_event", id="composer-input")
                        yield Button("Emit", id="send-event", variant="primary")
            with TabPane("Plugins", id="plugins-tab"):
                with Horizontal(id="plugin-panel"):
                    with Vertical(id="plugin-panel-left"):
                        yield Static("PLUGINS", classes="section-title")
                        for plugin in self._available_plugins():
                            yield self._plugin_row(plugin)
                    with Vertical(id="plugin-panel-right"):
                        yield Static("Plugin History", classes="section-title")
                        yield Static(id="plugin-history")
                        with Vertical(id="plugin-config-section"):
                            yield Static("Configuration", classes="section-title")
                            yield Static(id="plugin-config")
            with TabPane("Voices", id="voices-tab"):
                yield Static("RUNTIME VOICES", classes="section-title")
                yield Tree("Voices", id="voice-tree")
            with TabPane("Global Workflows", id="workflows-tab"):
                yield Static("WORKFLOW TREE", classes="section-title")
                yield Tree("Workflows", id="workflow-tree")
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
            self._controller = HotReloadController(
                manager=self.manager,
                watched_root=self.config_dir,
                loop=asyncio.get_running_loop(),
                replacement_factory=self.replacement_factory,
            )
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

    def on_switch_changed(self, event: Switch.Changed) -> None:
        switch_id = event.switch.id or ""
        if switch_id.startswith("switch-"):
            plugin_name = switch_id.removeprefix("switch-")
            self.run_worker(self._set_plugin(plugin_name, event.value), exclusive=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "send-event":
            self.query_one("#composer-input", Input).focus()
            self.run_worker(self._submit_composer(), exclusive=False)
            return
        if button_id.startswith("select-"):
            self._selected_plugin = button_id.removeprefix("select-")
            self._refresh_plugin_selection()
            self._refresh_view()
            return
        if button_id.startswith("apply-config-"):
            self.run_worker(self._configure_plugin(button_id.removeprefix("apply-config-")), exclusive=False)
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "composer-input":
            return
        value = event.value.strip()
        autocomplete = self.query_one("#event-autocomplete", ListView)
        if value.startswith("/"):
            prefix = value[1:].strip().lower()
            matching = [
                reg.name for reg in self.manager.get_event_registrations()
                if prefix in reg.name.lower()
            ]
            autocomplete.clear()
            for name in matching:
                autocomplete.append(ListItem(Label(name)))
            autocomplete.display = bool(matching)
        else:
            autocomplete.display = False

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        autocomplete = self.query_one("#event-autocomplete", ListView)
        if not autocomplete.display:
            return
        index = autocomplete.index
        if index is None:
            return
        input_widget = self.query_one("#composer-input", Input)
        prefix = input_widget.value.strip()[1:].lower()
        matching = [
            reg.name for reg in self.manager.get_event_registrations()
            if prefix in reg.name.lower()
        ]
        if index < len(matching):
            self._select_event(matching[index])
        autocomplete.display = False

    async def _submit_composer(self) -> None:
        input_widget = self.query_one("#composer-input", Input)
        value = input_widget.value.strip()
        if not value:
            return
        if value.startswith("/"):
            name = value[1:].strip()
            contract = next(
                (item.contract for item in self.manager.get_event_registrations() if item.name == name), None
            )
            if contract is None:
                self.notify(f"ERROR: unknown event /{name}", severity="error")
            else:
                self._select_event(name)
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
            self.notify(
                f"ERROR: invalid JSON for /{self._selected_event}: {error.errors()[0]['msg']}",
                severity="error",
            )
            self._refresh_view()
            return
        await self.manager.emit(self._selected_event, payload, source="tui")
        self._selected_event = None
        input_widget.value = ""
        self.query_one("#composer-mode", Label).update(
            "Composer: ordinary text → tui_event · /event_name → strict JSON payload"
        )

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
            self.notify(f"ERROR: unknown plugin configuration {name}", severity="error")
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
        self.notify(f"CONFIGURED {name}: microphone={microphone or 'default'}, speaker={speaker or 'default'}")
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
            self.notify(f"ERROR [{envelope.data.plugin}]: {envelope.data.message}", severity="error")
        self._update_voice_status(envelope)
        self._update_audio_status(envelope)

    def _refresh_view_after_event(self) -> None:
        if self.is_mounted:
            self.call_after_refresh(self._refresh_view)

    def _refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#event-state", Static).update(self.event_text or "waiting for events")
        self.query_one("#plugin-history", Static).update(self._history_text())
        self._refresh_plugin_switches()
        self._refresh_plugin_config()
        self._populate_event_tree()
        self._populate_voice_tree()
        self._populate_workflow_tree()
        self.query_one("#mcp-state", Static).update(self._mcp_state())

    def _refresh_plugin_switches(self) -> None:
        for plugin in self._available_plugins():
            try:
                self.query_one(f"#switch-{plugin.name}", Switch).value = plugin.enabled
            except Exception:
                pass
        for name, status in self._audio_status.items():
            try:
                self.query_one(f"#audio-status-{name}", Static).update(status)
            except Exception:
                pass

    def _refresh_plugin_config(self) -> None:
        section = self.query_one("#plugin-config-section", Vertical)
        name = self._selected_plugin
        if name is None:
            section.display = False
            return
        config = self._configuration_for(name)
        if config is None:
            section.display = False
            return
        section.display = True
        self.query_one("#plugin-config", Static).update(self._format_configuration(config))

    def _refresh_plugin_selection(self) -> None:
        for plugin in self._available_plugins():
            try:
                btn = self.query_one(f"#select-{plugin.name}", Button)
                btn.classes = "plugin-name selected" if plugin.name == self._selected_plugin else "plugin-name"
            except Exception:
                pass

    def _plugin_row(self, plugin: Plugin) -> Horizontal:
        enabled_status = "🟢" if plugin.enabled else "⚪"
        audio = self._audio_status.get(plugin.name, "?")
        selected_class = "plugin-name selected" if plugin.name == self._selected_plugin else "plugin-name"
        return Horizontal(
            Static(enabled_status, classes="plugin-status"),
            Button(plugin.name, id=f"select-{plugin.name}", classes=selected_class),
            Static(audio, id=f"audio-status-{plugin.name}"),
            Switch(value=plugin.enabled, id=f"switch-{plugin.name}"),
            classes="plugin-row",
        )

    def _available_plugins(self) -> tuple[Plugin, ...]:
        plugins: dict[str, Plugin] = {plugin.name: plugin for plugin in self.runtime.runtime_plugins}
        plugins.update({plugin.name: plugin for plugin in self.manager.get_plugins()})
        return tuple(plugins.values())

    def _history_text(self) -> str:
        name = self._selected_plugin
        if name is None:
            return "no plugin selected"
        history = self.manager.get_plugin_event_history(name)
        sent = (f"SENT  {self._format_event(event)}" for event in history.sent)
        received = (f"RECV  {self._format_event(event)}" for event in history.received)
        return f"{name}\n" + "\n".join((*sent, *received))

    def _configuration_for(self, name: str) -> TuiPluginConfiguration | None:
        if not isinstance(self.runtime, TuiConfigurationRuntime):
            return None
        return next((c for c in self.runtime.plugin_configurations if c.plugin == name), None)

    @staticmethod
    def _format_configuration(configuration: TuiPluginConfiguration) -> str:
        audio = ", ".join(
            value
            for value in (
                f"microphone={configuration.microphone}" if configuration.microphone else "",
                f"speaker={configuration.speaker}" if configuration.speaker else "",
            )
            if value
        )
        return f"{configuration.plugin}: {audio or 'configured'}"

    def _populate_voice_tree(self) -> None:
        tree = self.query_one("#voice-tree", Tree)
        tree.clear()
        for voice in self.runtime.workflow_voices:
            status = self._voice_status.get(voice, "idle")
            voice_node = tree.root.add(f"{voice} · {status.upper()}")
            try:
                definitions = self.runtime.workflow_catalog.discover(voice=voice)
            except WorkflowDefinitionError as error:
                voice_node.add_leaf(f"└ Catalog error: {error}")
                continue
            for definition in definitions:
                snapshot = self.runtime.workflow_engine.snapshot(workflow=definition.name, voice=voice)
                if snapshot is None:
                    voice_node.add_leaf(f"{definition.name} · ⚪ INACTIVE")
                    continue
                icon = self._status_icon(snapshot)
                wf_node = voice_node.add(f"{definition.name} · {icon} {snapshot.status.value.upper()}")
                phase = next(
                    (p for p in definition.phases if p.id.casefold() == snapshot.phase_id.casefold()), None
                )
                if phase:
                    phase_index = next(
                        i for i, p in enumerate(definition.phases) if p.id.casefold() == snapshot.phase_id.casefold()
                    )
                    wf_node.add_leaf(f"Phase: {phase.name} ({phase_index + 1}/{len(definition.phases)})")
                    wf_node.add_leaf(f"Task: {phase.instructions[0] if phase.instructions else '—'}")
                    completed = snapshot.phase_status is WorkflowPhaseStatus.DONE
                    wf_node.add_leaf(
                        f"Progress: {(len(phase.instructions) if completed else 0)}/{len(phase.instructions)} instructions"
                    )
                    wf_node.add_leaf(
                        f"Checkpoints: {(len(phase.checkpoints) if completed else 0)}/{len(phase.checkpoints)} ✓"
                    )
                else:
                    wf_node.add_leaf(f"Phase: {snapshot.phase_id}")
        tree.root.expand_all()

    def _populate_workflow_tree(self) -> None:
        tree = self.query_one("#workflow-tree", Tree)
        tree.clear()
        # Collect all unique workflows across all voices
        workflow_map: dict[str, dict[str, WorkflowDefinition]] = {}
        for voice in self.runtime.workflow_voices:
            try:
                definitions = self.runtime.workflow_catalog.discover(voice=voice)
            except WorkflowDefinitionError:
                continue
            for definition in definitions:
                workflow_map.setdefault(definition.name.casefold(), {})[voice] = definition
        if not workflow_map:
            tree.root.add_leaf("no workflows discovered")
            return
        # Build tree: workflow → voices → snapshot data
        for wf_name in sorted(workflow_map.keys()):
            voices = workflow_map[wf_name]
            # Pick the first voice's definition for metadata
            first_defn = next(iter(voices.values()))
            wf_node = tree.root.add(first_defn.name)
            for voice in sorted(voices.keys()):
                snapshot = self.runtime.workflow_engine.snapshot(workflow=first_defn.name, voice=voice)
                if snapshot is None:
                    wf_node.add_leaf(f"{voice} · ⚪ INACTIVE")
                else:
                    icon = self._status_icon(snapshot)
                    v_node = wf_node.add(f"{voice} · {icon} {snapshot.status.value.upper()}")
                    phase = next(
                        (p for p in first_defn.phases if p.id.casefold() == snapshot.phase_id.casefold()),
                        None,
                    )
                    if phase:
                        v_node.add_leaf(f"Phase: {phase.name}")
                        v_node.add_leaf(f"Task: {phase.instructions[0] if phase.instructions else '—'}")
        tree.root.expand_all()

    def _populate_event_tree(self) -> None:
        tree = self.query_one("#event-registrations-tree", Tree)
        tree.clear()
        for reg in self.manager.get_event_registrations():
            contract_name = reg.contract.__name__
            event_node = tree.root.add(f"{reg.name} ({contract_name})")
            params_node = event_node.add("Parameters")
            for field_name, field_info in reg.contract.model_fields.items():
                if field_name == "model_config":
                    continue
                type_hint = self._field_type_str(field_info)
                req = "required" if field_info.is_required() else ""
                default = ""
                if not field_info.is_required():
                    val = field_info.default
                    if val is None:
                        default = "default=None"
                    else:
                        default = f"default={val!r}"
                tag = f" [{req}]" if req else (f" [{default}]" if default else "")
                params_node.add_leaf(f"{field_name}: {type_hint}{tag}")
            if reg.receivers:
                subs_node = event_node.add("Subscribers")
                for plugin_name in reg.receivers:
                    subs_node.add_leaf(plugin_name)
        tree.root.expand_all()

    @staticmethod
    def _field_type_str(field_info: FieldInfo) -> str:
        annotation = field_info.annotation
        if annotation is None:
            return "Any"
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            args = annotation.__args__
            args_str = ", ".join(
                getattr(a, "__name__", str(a).removeprefix("typing.")) for a in args
            )
            origin_name = getattr(origin, "__name__", str(origin))
            return f"{origin_name}[{args_str}]"
        return getattr(annotation, "__name__", str(annotation))

    def _select_event(self, name: str) -> None:
        contract = next(
            (item.contract for item in self.manager.get_event_registrations() if item.name == name), None
        )
        if contract is None:
            return
        self._selected_event = name
        self.query_one("#composer-mode", Label).update(
            f"Payload for /{name}: strict JSON for {contract.__name__}"
        )
        template = self._json_template(contract)
        self.query_one("#composer-input", Input).value = template
        self.query_one("#composer-input", Input).focus()

    @staticmethod
    def _json_template(contract: type[BaseModel]) -> str:
        fields: dict[str, object] = {}
        for field_name, field_info in contract.model_fields.items():
            if field_name == "model_config":
                continue
            if field_info.is_required():
                annotation = field_info.annotation
                origin = getattr(annotation, "__origin__", None)
                if origin is list:
                    fields[field_name] = []
                elif origin is dict:
                    fields[field_name] = {}
                elif annotation is str:
                    fields[field_name] = ""
                elif annotation is int:
                    fields[field_name] = 0
                elif annotation is float:
                    fields[field_name] = 0.0
                elif annotation is bool:
                    fields[field_name] = False
                elif annotation is bytes:
                    fields[field_name] = ""
                else:
                    fields[field_name] = ""
            else:
                val = field_info.default
                if val is not None and not isinstance(val, type):
                    fields[field_name] = val
        return json.dumps(fields, indent=2, default=str)

    def _voice_text(self) -> str:
        return "\n".join(
            f"{voice} · {self._voice_status.get(voice, 'idle')}" for voice in self.runtime.workflow_voices
        ) or "no voices"

    def _update_voice_status(self, envelope: EventEnvelope[BaseModel]) -> None:
        if isinstance(envelope.data, VoiceStatusData) and envelope.data.voice in self.runtime.workflow_voices:
            self._voice_status[envelope.data.voice] = envelope.data.status.value

    def _update_audio_status(self, envelope: EventEnvelope[BaseModel]) -> None:
        status_data = envelope.data
        if isinstance(status_data, AudioInputStatusData | AudioOutputStatusData):
            plugin = envelope.source.split("/", maxsplit=1)[0]
            self._audio_status[plugin] = status_data.status.value

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
        return (
            "\n".join(
                f"{server.server_name} / {server.voice_name}: {runtime_status} · waits={server.pending_wait_count}"
                for server in self.runtime.mcp_servers
            )
            or "no MCP servers"
        )

    @staticmethod
    def _format_event(envelope: EventEnvelope[BaseModel]) -> str:
        data = envelope.data
        if isinstance(data, TuiEventData | PluginErrorData):
            message = data.message
        else:
            message = type(data).__name__
        return f"{envelope.name:<22} {envelope.source:<16} {message}"


def run_tui(*, fixture: bool = False, config_dir: Path | None = None) -> None:
    resolved_config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
    if fixture:
        runtime: TuiRuntime = _FixtureRuntime(resolved_config_dir)
    else:
        from kateto.core.config import load_config
        from kateto.run_mode import build_runtime_owner

        runtime = build_runtime_owner(load_config(config_dir=resolved_config_dir))
    KatetoApp(runtime=runtime, fixture=fixture, config_dir=resolved_config_dir).run()
