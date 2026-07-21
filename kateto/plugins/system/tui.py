from __future__ import annotations

import json
import asyncio  # noqa: ANYIO_OK
from collections.abc import AsyncIterator
from collections import deque
from pathlib import Path
from typing import Any, assert_never

from pydantic import BaseModel, Field, ValidationError
from pydantic.fields import FieldInfo
from rich.text import Text as RichText
from textual.app import App, ComposeResult, Screen
from textual.containers import Grid, Horizontal, Vertical
from textual.events import Click
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, Switch, TabbedContent, TabPane, Tree

from kateto.core.event import (
    AudioInputStatusData,
    AudioOutputStatusData,
    EventEnvelope,
    EventModel,
    GenerateData,
    PluginErrorData,
    TextChunk,
    VoiceRequestData,
    VoiceStatus,
    VoiceStatusData,
    WorkflowCheckpointResult,
    WorkflowPhaseCompleteData,
    WorkflowRunData,
)
from kateto.core.config import VoiceSettings, bootstrap_config
from kateto.core.hot_reload import HotReloadController, ReloadContext, ReplacementFactory
from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin
from kateto.core.workflow import WorkflowCatalog, WorkflowDefinition, WorkflowDefinitionError, WorkflowPhaseStatus, WorkflowStatus
from kateto.core.workflow_engine import WorkflowSnapshot
from kateto.plugins.system.tui_runtime import TuiConfigurationRuntime, TuiPluginConfiguration
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole


class TuiEventData(EventModel):
    message: str = Field(min_length=1)


class _FixtureVoiceProvider:
    """Deterministic provider used by the local TUI fixture."""

    def __init__(self, voice: str, role_response: str) -> None:
        self._voice = voice
        self._role_response = role_response

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        return self._stream(request)

    async def _stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        prompt = next(
            (message.content for message in reversed(request.messages) if message.role == "user"),
            "the current project",
        )
        yield f"{self._voice.title()} fixture response: {self._role_response} I received '{prompt}'."


class _FixtureVoice(VoiceAgent):
    async def on_voice_request(self, data: VoiceRequestData) -> None:
        await super().on_voice_request(data)
        if data.workflow is None or data.phase_id is None or self.manager is None:
            return
        definition = WorkflowCatalog(config_dir=self._config_dir).load(workflow=data.workflow, voice=self.name)
        if definition.voice is not None and definition.voice.casefold() != self.name.casefold():
            return
        phase = next(
            phase for phase in definition.phases if phase.id.casefold() == data.phase_id.casefold()
        )
        await self.manager.emit(
            "workflow_phase_complete",
            WorkflowPhaseCompleteData(
                workflow=definition.name,
                phase_id=phase.id,
                voice=self.name,
                deliverables=list(phase.deliverables),
                checkpoint_results=[
                    WorkflowCheckpointResult(checkpoint=checkpoint, passed=True)
                    for checkpoint in phase.checkpoints
                ],
            ),
            source=self.name,
            target="workflow_engine",
        )


def _fixture_voice(name: str, config_dir: Path) -> VoiceAgent:
    profiles = {
        "jane": (
            VoiceRole.ORCHESTRATOR,
            "Coordinate the project and keep the team aligned.",
            "I will coordinate the project and keep the team aligned.",
        ),
        "doktor": (
            VoiceRole.DELIVERY_ADVISOR,
            "Turn project intent into concrete delivery work.",
            "I will focus on delivery risks, backlog work, and concrete next steps.",
        ),
        "conquest": (
            VoiceRole.AGILE_FACILITATOR,
            "Make the team's process and next steps visible.",
            "I will facilitate the agile process and make the next ceremony steps visible.",
        ),
    }
    role, prompt, role_response = profiles[name]
    voice_dir = config_dir / "voices" / name
    voice_dir.mkdir(parents=True, exist_ok=True)
    reference = voice_dir / "reference.wav"
    if not reference.exists():
        reference.write_bytes(b"RIFFfixtureWAVE")
    return _FixtureVoice(
        profile=VoiceProfile(
            voice_id=name,
            display_name=name.title(),
            role=role,
            system_prompt=prompt,
            relevance_terms=frozenset(),
        ),
        config_dir=config_dir,
        provider=_FixtureVoiceProvider(name, role_response),
        settings=VoiceSettings(stream=True),
        response_language="en",
    )


class _FixtureRuntime:
    def __init__(self, config_dir: Path) -> None:
        from kateto.core.workflow_engine import WorkflowEngine

        config_dir = config_dir.resolve()
        bootstrap_config(config_dir=config_dir)
        self.manager = PluginManager()
        self._workflow_engine = WorkflowEngine(config_dir=config_dir)
        self._voices = tuple(_fixture_voice(name, config_dir) for name in ("jane", "doktor", "conquest"))
        self.runtime_plugins = (self._workflow_engine, *self._voices)
        self.mcp_servers = ()
        self.workflow_voices = ("jane", "doktor", "conquest")
        self.hot_reload_controller = None
        self.is_started = False
        self.plugin_configurations = ()

    @property
    def workflow_catalog(self):
        return self._workflow_engine.catalog

    @property
    def workflow_engine(self):
        return self._workflow_engine

    def voice_enabled(self, name: str) -> bool:
        return True

    async def start(self) -> None:
        for plugin in self.runtime_plugins:
            await self.manager.enable_plugin(plugin)
        await self.manager.emit("tui_event", TuiEventData(message="fixture dashboard ready"), source="fixture")
        await self.manager.emit(
            "workflow_run",
            WorkflowRunData(workflow="project-initiation", voice="jane"),
            source="fixture",
        )
        self.is_started = True

    async def stop(self) -> None:
        await self.manager.close()
        self.is_started = False


class EventDetailScreen(Screen[None]):
    def __init__(self, event_name: str, source: str, data_json: str) -> None:
        super().__init__()
        self.event_name = event_name
        self.source = source
        self.data_json = data_json

    CSS = """
    EventDetailScreen { align: center middle; background: $surface 80%; }
    #detail-box { width: 80%; height: 80%; border: thick $accent; background: $surface; padding: 2; overflow-y: auto; }
    #detail-box > Static { height: auto; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-box"):
            header = RichText(self.event_name, style="bold")
            header.append(f" from {self.source}")
            yield Static(header)
            yield Static(RichText(self.data_json))
            yield Button("Close", id="close-detail", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-detail":
            self.app.pop_screen()

    def key_escape(self) -> None:
        self.app.pop_screen()


class KatetoApp(App[None]):
    CSS = """
    Screen { layout: vertical; background: $surface; }
    #workspace { height: 1fr; min-height: 0; }
    TabbedContent { height: 1fr; }
    .section-title { color: $accent; text-style: bold; margin-bottom: 1; }

    /* Events tab */
    #events-body { height: 1fr; margin-bottom: 1; }
    #events-content { height: 100%; }
    #events-stream { width: 1fr; height: 100%; border: solid $secondary; padding: 1; }
    #event-list { height: 1fr; min-height: 0; }
    #events-registrations { width: 40%; height: 100%; border: round $secondary; padding: 1; }
    #event-registrations-tree { height: 1fr; overflow-y: auto; min-height: 0; }
    #composer { dock: bottom; height: 5; padding: 0 1; }
    #composer-input { width: 1fr; }
    #send-event { width: 16; }

    /* Plugins tab */
    #plugin-panel { height: 1fr; }
    #plugin-panel-left { width: 40%; min-width: 16; height: 1fr; overflow-y: auto; border: round $secondary; padding: 1; }
    #plugin-panel-right { width: 1fr; height: 1fr; border: round $secondary; padding: 1; }
    #plugin-list { height: auto; }
    .plugin-row { width: 1fr; height: 3; grid-size: 3; grid-columns: 1fr auto auto; }
    .plugin-name { width: 1fr; min-width: 1; padding: 0 1; }
    .plugin-switch { width: 10; min-width: 10; margin: 0; }
    .plugin-name.selected { background: $accent; color: $surface; }
    #plugin-history { height: auto; max-height: 12; overflow-y: auto; min-height: 0; border-top: solid $secondary; margin-top: 1; padding: 1; }
    #plugin-config-section { height: auto; max-height: 12; overflow-y: auto; border-top: solid $secondary; margin-top: 1; padding: 1; }
    #event-autocomplete { height: auto; max-height: 10; border: solid $secondary; display: none; overflow-y: auto; }

    /* Voices tab */
    #voice-tree { height: 1fr; }

    /* Workflows tab */
    #workflow-tree { height: 1fr; }

    /* MCPs tab */
    #mcp-state { height: 1fr; border: solid $secondary; padding: 1; overflow-y: auto; }
    /* Conversation tab */
    #conversation-tab { layout: vertical; }
    #conversation-body { height: 1fr; min-height: 0; overflow-y: auto; border: solid $secondary; padding: 1; }
    #conversation-messages { height: auto; margin-bottom: 1; }
    .chat-message { height: auto; margin-bottom: 1; padding: 1 2; }
    .chat-user { background: $primary 20%; border-left: thick $primary; }
    .chat-agent { background: $accent 20%; border-left: thick $accent; }
    #conversation-input { dock: bottom; height: 3; padding: 0 1; }
    #conversation-input > Input { width: 1fr; }
    #conversation-input > Button { width: 12; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]

    def __init__(
        self,
        *,
        runtime: Any,
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
        self._events: deque[EventEnvelope[BaseModel]] = deque(maxlen=1000)
        self._voice_status: dict[str, str] = {voice: "idle" for voice in runtime.workflow_voices}
        self._audio_status: dict[str, str] = {}
        self._selected_plugin: str | None = None
        self._selected_event: str | None = None
        self._controller: HotReloadController | None = None
        self._stop_runtime_started = False
        self._voice_texts: dict[str, str] = {}
        self._voice_bubble_seq: dict[str, int] = {}
        self._pending_refresh = False
        self._last_tree_refresh = 0.0
        self.manager.register_event("tui_event", TuiEventData)
        self.manager.add_event_observer(self._observe_event)

    @property
    def event_text(self) -> str:
        return "\n".join(self._format_event(e) for e in self._events) or "waiting for events"

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
                            yield ListView(id="event-list")
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
            with TabPane("Conversation", id="conversation-tab"):
                with Vertical(id="conversation-body"):
                    with Vertical(id="conversation-messages"):
                        yield Static("no messages yet", id="conversation-placeholder")
                with Horizontal(id="conversation-input"):
                    yield Input(placeholder="Type a prompt for the agent...", id="prompt-input")
                    yield Button("Send", id="send-prompt", variant="primary")
            with TabPane("Plugins", id="plugins-tab"):
                with Horizontal(id="plugin-panel"):
                    with Vertical(id="plugin-panel-left"):
                        yield Static("PLUGINS", classes="section-title")
                        yield Vertical(id="plugin-list")
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

    def on_click(self, event: Click) -> None:
        widget = event.widget
        if widget is None:
            return
        widget_id = widget.id or ""
        if widget_id.startswith("select-"):
            self._select_plugin(widget_id.removeprefix("select-"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "send-event":
            self.query_one("#composer-input", Input).focus()
            self.run_worker(self._submit_composer(), exclusive=False)
            return
        if button_id == "send-prompt":
            self.run_worker(self._submit_prompt(), exclusive=False)
            return
        if button_id.startswith("select-"):
            self._select_plugin(button_id.removeprefix("select-"))
            return
        if button_id.startswith("apply-config-"):
            self.run_worker(self._configure_plugin(button_id.removeprefix("apply-config-")), exclusive=False)
            return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "prompt-input":
            self.run_worker(self._submit_prompt(), exclusive=False)
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
        list_view = event.list_view
        if list_view.id == "event-autocomplete":
            index = list_view.index
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
            list_view.display = False
        elif list_view.id == "event-list":
            index = list_view.index
            if index is None:
                return
            events = list(self._events)
            if 0 <= index < len(events):
                envelope = events[index]
                data_json = self._safe_event_json(envelope.data)
                self.push_screen(EventDetailScreen(
                    event_name=envelope.name,
                    source=envelope.source,
                    data_json=data_json,
                ))

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

    async def _submit_prompt(self) -> None:
        input_widget = self.query_one("#prompt-input", Input)
        text = input_widget.value.strip()
        if not text:
            return
        input_widget.value = ""
        self._add_chat_message("user", "You", text)
        await self.manager.emit("generate", GenerateData(prompt=text), source="tui")

    def _add_chat_message(self, role: str, name: str, content: str) -> None:
        if not self.is_mounted:
            return
        messages = self.query_one("#conversation-messages", Vertical)
        placeholder = messages.query("#conversation-placeholder")
        if placeholder:
            placeholder.remove()
        self._hide_typing_indicator(name)
        self._voice_texts.pop(name, None)
        msg = Static(self._chat_renderable(name, content), classes=f"chat-message chat-{role}")
        messages.mount(msg)
        self.query_one("#conversation-body", Vertical).scroll_end(animate=False)

    def _show_typing_indicator(self, voice: str) -> None:
        if not self.is_mounted:
            return
        indicator_id = f"typing-{voice}"
        existing = self.query(f"#{indicator_id}")
        if existing:
            return
        messages = self.query_one("#conversation-messages", Vertical)
        placeholder = messages.query("#conversation-placeholder")
        if placeholder:
            placeholder.remove()
        msg = Static(
            self._chat_renderable(voice, "…", dim=True),
            id=indicator_id,
            classes="chat-message chat-agent",
        )
        messages.mount(msg)
        self.query_one("#conversation-body", Vertical).scroll_end(animate=False)

    def _hide_typing_indicator(self, voice: str) -> None:
        if not self.is_mounted:
            return
        indicator = self.query(f"#typing-{voice}")
        if indicator:
            indicator.remove()

    def _handle_text_chunk(self, voice: str, chunk: TextChunk) -> None:
        if not self.is_mounted:
            return
        messages = self.query_one("#conversation-messages", Vertical)
        placeholder = messages.query("#conversation-placeholder")
        if placeholder:
            placeholder.remove()
        self._hide_typing_indicator(voice)
        seq = self._voice_bubble_seq.get(voice, 0)
        bubble_id = f"bubble-{voice}-{seq}"
        self._voice_texts.setdefault(bubble_id, "")
        self._voice_texts[bubble_id] += chunk.text
        existing = messages.query(Static).filter(f"#{bubble_id}")
        if existing:
            existing.first().update(self._chat_renderable(voice, self._voice_texts[bubble_id]))
        else:
            msg = Static(
                self._chat_renderable(voice, self._voice_texts[bubble_id]),
                id=bubble_id,
                classes="chat-message chat-agent",
            )
            messages.mount(msg)
        if chunk.final:
            self._voice_bubble_seq[voice] = seq + 1
        self.query_one("#conversation-body", Vertical).scroll_end(animate=False)

    @staticmethod
    def _chat_renderable(name: str, content: str, *, dim: bool = False) -> RichText:
        renderable = RichText(name, style="bold")
        renderable.append("  ")
        renderable.append(content, style="dim" if dim else None)
        return renderable

    async def _emit_manual(self, message: str) -> None:
        await self.manager.emit("tui_event", TuiEventData(message=message), source="tui")

    async def _set_plugin(self, name: str, enabled: bool) -> None:
        if enabled:
            plugin = next((item for item in self._available_plugins() if item.name == name), None)
            if plugin is not None:
                await self.manager.enable_plugin(plugin)
        else:
            await self.manager.disable_plugin(name)
        self._refresh_plugin_switches()
        self._refresh_plugin_config()

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
        return Plugin(plugin.name, capabilities=plugin.capabilities)

    def _record_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        self._update_voice_status(envelope)
        self._update_audio_status(envelope)
        self._events.append(envelope)

    def _observe_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        if not self.is_mounted:
            return
        self._record_event(envelope)
        try:
            self.query_one("#event-list", ListView).append(ListItem(Label(self._format_event(envelope))))
        except Exception:
            pass
        if isinstance(envelope.data, PluginErrorData):
            self.notify(f"ERROR [{envelope.data.plugin}]: {envelope.data.message}", severity="error")
        self._refresh_light()
        self._schedule_tree_refresh()
        source_voice = envelope.source.split("/")[0]
        if source_voice not in self.runtime.workflow_voices:
            return
        if isinstance(envelope.data, VoiceStatusData):
            if envelope.data.status in (VoiceStatus.WAITING, VoiceStatus.THINKING):
                self._show_typing_indicator(source_voice)
            elif envelope.data.status == VoiceStatus.IDLE:
                self._hide_typing_indicator(source_voice)
            return
        if isinstance(envelope.data, TextChunk):
            self._handle_text_chunk(source_voice, envelope.data)
            return
        data_preview = str(envelope.data)
        if len(data_preview) > 200:
            data_preview = data_preview[:197] + "..."
        self._add_chat_message("agent", source_voice, data_preview)

    def _refresh_light(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#plugin-history", Static).update(self._history_text())
        self._refresh_plugin_config()
        self.query_one("#mcp-state", Static).update(self._mcp_state())

    def _schedule_tree_refresh(self) -> None:
        now = asyncio.get_event_loop().time()
        if now - self._last_tree_refresh < 1.0:
            return
        self._last_tree_refresh = now
        if not self.is_mounted:
            return
        self._populate_plugin_list()
        self._populate_event_tree()
        self._populate_voice_tree()
        self._populate_workflow_tree()

    def _refresh_view(self) -> None:
        self._refresh_light()
        self._last_tree_refresh = asyncio.get_event_loop().time()
        if not self.is_mounted:
            return
        self._populate_plugin_list()
        self._populate_event_tree()
        self._populate_voice_tree()
        self._populate_workflow_tree()

    def _populate_plugin_list(self) -> None:
        container = self.query_one("#plugin-list", Vertical)
        container.remove_children()
        for plugin in self._available_plugins():
            container.mount(self._plugin_row(plugin))

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
                label = self.query_one(f"#select-{plugin.name}", Static)
                label.classes = "plugin-name selected" if plugin.name == self._selected_plugin else "plugin-name"
            except Exception:
                pass

    def _select_plugin(self, plugin_name: str) -> None:
        self._selected_plugin = plugin_name
        self._refresh_plugin_selection()
        self._refresh_view()

    def _plugin_row(self, plugin: Plugin) -> Grid:
        audio = self._audio_status.get(plugin.name, "?")
        selected_class = "plugin-name selected" if plugin.name == self._selected_plugin else "plugin-name"
        return Grid(
            Static(plugin.name, id=f"select-{plugin.name}", classes=selected_class),
            Static(audio, id=f"audio-status-{plugin.name}"),
            Switch(value=plugin.enabled, animate=False, id=f"switch-{plugin.name}", classes="plugin-switch"),
            classes="plugin-row",
        )

    def _available_plugins(self) -> tuple[Plugin, ...]:
        plugins = {plugin.name: plugin for plugin in self.manager.get_plugins()}
        if not plugins:
            plugins = {plugin.name: plugin for plugin in self.runtime.runtime_plugins}
        config = getattr(self.runtime, "config", None)
        if config is not None:
            for name in config.settings.plugin:
                if name not in plugins:
                    p = Plugin(name)
                    p.enabled = config.settings.plugin[name].enabled
                    plugins[name] = p
            for name in config.settings.voice:
                if name in plugins:
                    continue
                plugin_name = f"voice_{name}"
                if plugin_name not in plugins:
                    p = Plugin(plugin_name)
                    p.enabled = config.settings.voice[name].enabled
                    plugins[plugin_name] = p
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
            enabled = self.runtime.voice_enabled(voice)
            tag = "✅" if enabled else "⛔"
            label = f"{tag} {voice} · {status.upper()}"
            if not enabled:
                label += " (disabled)"
            voice_node = tree.root.add(label)
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
        return json.dumps(fields, default=str)

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
    def _safe_event_json(data: BaseModel) -> str:
        try:
            data_str = data.model_dump_json(exclude_none=True)
        except Exception:
            fields = {
                k: f"<{type(v).__name__} {len(v)} bytes>" if isinstance(v, bytes) else v
                for k, v in data.__dict__.items()
            }
            try:
                data_str = json.dumps(fields, default=str)
            except Exception:
                data_str = str(data)
        if len(data_str) > 4096:
            data_str = data_str[:4093] + "..."
        return data_str

    @staticmethod
    def _format_event(envelope: EventEnvelope[BaseModel]) -> str:
        data_str = KatetoApp._safe_event_json(envelope.data)
        if len(data_str) > 60:
            data_str = data_str[:57] + "..."
        return f"{envelope.name:<22} {envelope.source:<16} {data_str}"


def run_tui(*, fixture: bool = False, config_dir: Path | None = None) -> None:
    from kateto.core.config import resolve_config_dir as _resolve_config_dir

    resolved_config_dir = (_resolve_config_dir() if config_dir is None else config_dir).resolve()
    if fixture:
        runtime: Any = _FixtureRuntime(resolved_config_dir)
    else:
        from kateto.core.config import load_config
        from kateto.run_mode import build_runtime_owner

        runtime = build_runtime_owner(load_config(config_dir=resolved_config_dir))
    KatetoApp(runtime=runtime, fixture=fixture, config_dir=resolved_config_dir).run()
