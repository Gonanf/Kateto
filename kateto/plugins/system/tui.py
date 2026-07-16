from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from pathlib import Path
from typing import assert_never

from pydantic import BaseModel, Field
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static

from kateto.core.event import EventEnvelope, EventModel, PluginErrorData
from kateto.core.hot_reload import HotReloadController, ReloadContext, ReplacementFactory
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowDefinition, WorkflowDefinitionError, WorkflowPhaseStatus, WorkflowStatus
from kateto.core.workflow_engine import WorkflowSnapshot
from kateto.plugins.system.tui_runtime import TuiRuntime


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
        self.workflow_voices = ()
        self.hot_reload_controller = None
        self.is_started = False

    @property
    def workflow_catalog(self):
        return self._workflow_engine.catalog

    @property
    def workflow_engine(self):
        return self._workflow_engine

    async def start(self) -> None:
        for plugin in self.runtime_plugins:
            await self.manager.enable_plugin(plugin)
        await self.manager.emit(
            "tui_event",
            TuiEventData(message="fixture dashboard ready"),
            source="fixture",
        )
        self.is_started = True

    async def stop(self) -> None:
        await self.manager.close()
        self.is_started = False


class KatetoApp(App[None]):
    CSS = (
        "Screen { layout: vertical; background: $surface; }"
        "#body { height: 1fr; min-height: 0; }"
        "#plugins { width: 42%; min-width: 0; border: round $primary; padding: 0 1; }"
        "#events { width: 58%; min-width: 0; border: round $secondary; padding: 0 1; overflow-y: auto; }"
        "#manual { dock: bottom; height: 3; }"
        "#manual-message { width: 1fr; }"
        "#send-event { width: 16; min-width: 16; }"
        ".plugin-row { height: 3; width: 1fr; }"
        ".plugin-name { width: 16; min-width: 16; content-align: left middle; }"
        ".plugin-row Button { width: 1fr; min-width: 0; border: none; background: transparent; }"
    )
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit"), ("enter", "quit", "Quit")]

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
        self.replacement_factory = replacement_factory
        if fixture and replacement_factory is None:
            self.replacement_factory = self._fixture_replacement_factory
        self._events: list[str] = []
        self._plugin_state = ""
        self._mcp_state = ""
        self._workflow_state = ""
        self._runtime_state = ""
        self._controller: HotReloadController | None = None
        self._stop_runtime_started = False
        self.manager.add_event_observer(self._observe_event)

    @property
    def plugin_text(self) -> str:
        return self._plugin_state

    @property
    def mcp_text(self) -> str:
        return self._mcp_state

    @property
    def workflow_text(self) -> str:
        return self._workflow_state

    @property
    def runtime_text(self) -> str:
        return self._runtime_state

    @property
    def event_text(self) -> str:
        return "\n".join(self._events)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="plugins"):
                yield Label("PLUGINS / VOICES", classes="title")
                yield Static(id="runtime-state")
                yield Static(id="plugin-state")
                yield Label("MCP SERVERS", classes="title")
                yield Static(id="mcp-state")
                yield Label("WORKFLOWS", classes="title")
                yield Static(id="workflow-state")
                for plugin in self._available_plugins():
                    yield self._plugin_controls(plugin)[0]
            with Vertical(id="events"):
                yield Label("EVENT STREAM", classes="title")
                yield Static(id="event-state")
        with Horizontal(id="manual"):
            yield Input(placeholder="manual event message", id="manual-message")
            yield Button("Send event", id="send-event", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self._events.extend(self._format_event(event) for event in self.manager.get_events())
        self._refresh_view()
        self.run_worker(self._start_runtime, exclusive=True)

    async def _start_runtime(self) -> None:
        await self.runtime.start()
        if self.fixture and self.runtime.hot_reload_controller is None:
            controller = HotReloadController(
                manager=self.manager,
                watched_root=self.config_dir,
                loop=asyncio.get_running_loop(),
                replacement_factory=self.replacement_factory,
            )
            self._controller = controller
            await controller.start()
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
            message = self.query_one("#manual-message", Input).value.strip()
            if message:
                self.run_worker(self._emit_manual(message), exclusive=False)
                self.query_one("#manual-message", Input).value = ""
            return
        prefix, _, name = button_id.partition("-")
        if prefix in {"enable", "disable"} and name:
            self.run_worker(self._set_plugin(name, prefix == "enable"), exclusive=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            self.run_worker(self.action_quit, exclusive=True)

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

    @staticmethod
    def _fixture_replacement_factory(plugin: Plugin, _context: ReloadContext) -> Plugin:
        return _FixturePlugin(plugin.name)

    def _observe_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        self._events.append(self._format_event(envelope))
        if self.is_mounted:
            self.call_after_refresh(self._refresh_view)

    def _refresh_view(self) -> None:
        if not self.is_mounted:
            return
        self._runtime_state = f"RUNTIME: {'RUNNING' if self.runtime.is_started else 'STOPPED'}"
        self._plugin_state = "\n".join(
            f"{plugin.name:<24} {'ON' if plugin.enabled else 'OFF'}"
            for plugin in self._available_plugins()
        ) or "no plugins"
        runtime_status = "READY" if self.runtime.is_started else "STOPPED"
        self._mcp_state = "\n".join(
            f"{server.server_name} / {server.voice_name}: {runtime_status}"
            for server in self.runtime.mcp_servers
        ) or "no MCP servers"
        self._workflow_state = self._format_workflows()
        self.query_one("#runtime-state", Static).update(self._runtime_state)
        self.query_one("#plugin-state", Static).update(self._plugin_state)
        self.query_one("#mcp-state", Static).update(self._mcp_state)
        self.query_one("#workflow-state", Static).update(self._workflow_state)
        self.query_one("#event-state", Static).update(self.event_text or "waiting for events")

    def _available_plugins(self) -> tuple[Plugin, ...]:
        plugins: dict[str, Plugin] = {plugin.name: plugin for plugin in self.runtime.runtime_plugins}
        plugins.update({plugin.name: plugin for plugin in self.manager.get_plugins()})
        return tuple(plugins.values())

    def _format_workflows(self) -> str:
        groups: list[str] = []
        for voice in self.runtime.workflow_voices:
            try:
                definitions = self.runtime.workflow_catalog.discover(voice=voice)
            except WorkflowDefinitionError as error:
                groups.append(f"{voice} · — · ⚪ INACTIVE\n  └ Catalog error: {error}")
                continue
            if not definitions:
                groups.append(f"{voice} · — · ⚪ INACTIVE")
                continue
            groups.extend(
                self._format_workflow(definition, voice)
                for definition in definitions
            )
        return "\n\n".join(groups) or "no workflows"

    def _format_workflow(self, definition: WorkflowDefinition, voice: str) -> str:
        snapshot = self.runtime.workflow_engine.snapshot(workflow=definition.name, voice=voice)
        if snapshot is None:
            return f"{voice} · {definition.name} · ⚪ INACTIVE"
        phase_index, phase = next(
            (index, phase)
            for index, phase in enumerate(definition.phases)
            if phase.id.casefold() == snapshot.phase_id.casefold()
        )
        icon = self._status_icon(snapshot)
        completed = snapshot.phase_status is WorkflowPhaseStatus.DONE
        instruction_count = len(phase.instructions)
        checkpoint_count = len(phase.checkpoints)
        instruction_progress = instruction_count if completed else 0
        checkpoint_progress = checkpoint_count if completed else 0
        return "\n".join(
            (
                f"{voice} · {definition.name} · {icon} {snapshot.status.value.upper()}",
                f"  ├ Fase activa: {phase.name} ({phase_index + 1}/{len(definition.phases)})",
                f"  ├ Progreso: {instruction_progress}/{instruction_count} instrucciones",
                f"  └ Checkpoints: {checkpoint_progress}/{checkpoint_count} ✓",
            ),
        )

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

    @staticmethod
    def _format_event(envelope: EventEnvelope[BaseModel]) -> str:
        data = envelope.data
        if isinstance(data, TuiEventData):
            message = data.message
        elif isinstance(data, PluginErrorData):
            message = data.message
        else:
            message = type(data).__name__
        return f"{envelope.name:<22} {envelope.source:<16} {message}"

    @staticmethod
    def _plugin_controls(plugin: Plugin) -> tuple[Horizontal, ...]:
        return (
            Horizontal(
                Label(plugin.name, classes="plugin-name"),
                Button("On", id=f"enable-{plugin.name}"),
                Button("Off", id=f"disable-{plugin.name}"),
                classes="plugin-row",
            ),
        )


def run_tui(*, fixture: bool = False, config_dir: Path | None = None) -> None:
    resolved_config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
    if fixture:
        runtime: TuiRuntime = _FixtureRuntime(resolved_config_dir)
    else:
        from kateto.core.config import load_config
        from kateto.run_mode import build_runtime_owner

        runtime = build_runtime_owner(load_config(config_dir=resolved_config_dir))
    KatetoApp(runtime=runtime, fixture=fixture, config_dir=resolved_config_dir).run()
