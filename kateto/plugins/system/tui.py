from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, Static

from kateto.core.event import EventEnvelope, EventModel, PluginErrorData
from kateto.core.hot_reload import HotReloadController, ReloadContext, ReplacementFactory
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin


class TuiEventData(EventModel):
    message: str = Field(min_length=1)


class _FixturePlugin(Plugin):
    def __init__(self, name: str) -> None:
        super().__init__(name, capabilities=("fixture",))


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
        manager: PluginManager,
        fixture: bool = False,
        config_dir: Path | None = None,
        replacement_factory: ReplacementFactory | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.fixture = fixture
        self.config_dir = (Path.cwd() if config_dir is None else config_dir).resolve()
        self.replacement_factory = replacement_factory
        if fixture and replacement_factory is None:
            self.replacement_factory = self._fixture_replacement_factory
        self._fixture_names = ("voice_jane", "voice_doktor", "voice_conquest", "workflow_engine")
        self._events: list[str] = []
        self._plugin_state = ""
        self._controller: HotReloadController | None = None
        self.manager.add_event_observer(self._observe_event)

    @property
    def plugin_text(self) -> str:
        return self._plugin_state

    @property
    def event_text(self) -> str:
        return "\n".join(self._events)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="plugins"):
                yield Label("PLUGINS / VOICES", classes="title")
                yield Static(id="plugin-state")
                for plugin in self.manager.get_plugins():
                    yield from self._plugin_controls(plugin)
                if self.fixture and not self.manager.get_plugins():
                    for name in self._fixture_names:
                        yield from self._plugin_controls(_FixturePlugin(name))
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
        if self.fixture:
            self.run_worker(self._bootstrap_fixture, exclusive=True)
        self.run_worker(self._start_hot_reload, exclusive=True)

    async def _bootstrap_fixture(self) -> None:
        for name in self._fixture_names:
            await self.manager.enable_plugin(_FixturePlugin(name))
        await self.manager.emit("tui_event", TuiEventData(message="fixture dashboard ready"), source="fixture")
        self._refresh_view()

    async def _start_hot_reload(self) -> None:
        controller = HotReloadController(
            manager=self.manager,
            watched_root=self.config_dir,
            loop=asyncio.get_running_loop(),
            replacement_factory=self.replacement_factory,
        )
        self._controller = controller
        await controller.start()

    def on_unmount(self) -> None:
        self.manager.remove_event_observer(self._observe_event)
        if self._controller is not None:
            self.run_worker(self._close_hot_reload, exclusive=True)

    async def _close_hot_reload(self) -> None:
        if self._controller is not None:
            await self._controller.close()
            self._controller = None

    async def action_quit(self) -> None:
        if self._controller is not None:
            await self._controller.close()
            self._controller = None
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
            plugin = next((item for item in self.manager.get_plugins() if item.name == name), None)
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
        states = [f"{plugin.name:<24} {'ON' if plugin.enabled else 'OFF'}" for plugin in self.manager.get_plugins()]
        self._plugin_state = "\n".join(states) or "no plugins"
        self.query_one("#plugin-state", Static).update(self._plugin_state)
        self.query_one("#event-state", Static).update(self.event_text or "waiting for events")

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
    manager = PluginManager()
    app = KatetoApp(manager=manager, fixture=fixture, config_dir=config_dir)
    app.run()
