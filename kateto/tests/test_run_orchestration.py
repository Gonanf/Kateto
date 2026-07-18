from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from kateto.core.config import load_config
from kateto.core.hot_reload import HotReloadController
from kateto.core.plugin import Plugin
from kateto.core.discovery import LiveAssemblyConfigurationError as EventRuntimeConfigurationError
from kateto.plugins.audio_input.base import AudioInputConfig
from kateto.run_mode import RuntimeDependencies, RuntimeOwner, build_runtime_owner, run_event_runtime
from kateto.plugins.system.tui_runtime import TuiPluginConfiguration


class QuietVad:
    def is_speech(self, samples: bytes) -> bool:
        return bool(samples) and False


class RecordingCapture:
    def __init__(self, started: asyncio.Event) -> None:
        self._started: asyncio.Event = started
        self.closed: bool = False

    def start(self) -> None:
        self._started.set()

    def stop(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class RecordingCaptureFactory:
    def __init__(self) -> None:
        self.started: asyncio.Event = asyncio.Event()
        self.captures: list[RecordingCapture] = []

    def create(self, config: AudioInputConfig, callback: Callable) -> RecordingCapture:
        del config, callback
        capture = RecordingCapture(self.started)
        self.captures.append(capture)
        return capture


class RecordingCalendar(Plugin):
    def __init__(self) -> None:
        super().__init__("connector_calendar", capabilities=("calendar",))


class CalendarFactory:
    def __init__(self) -> None:
        self.connector: RecordingCalendar | None = None

    def __call__(self, config_dir: Path) -> RecordingCalendar:
        del config_dir
        connector = RecordingCalendar()
        self.connector = connector
        return connector


class ReloadStartFailure(Exception):
    pass


def _write_run_config(config_dir: Path) -> None:
    _ = (config_dir / "config.toml").write_text(
        """
[kateto]
hot_reload = true

[plugin.audio_input_mic]
enabled = true
device = "fixture-input"
sample_rate = 16000
silence_timeout = 0.1
vad_model = "silero"

[plugin.audio_processor_whisper]
enabled = true
endpoint = "http://127.0.0.1:8090"

[plugin.executor_classifier]
enabled = true
model_endpoint = "http://127.0.0.1:8091"
model = "fixture-classifier"

[plugin.voice_llm]
enabled = true
endpoint = "http://127.0.0.1:8092/v1"
model = "fixture-voice"

[plugin.audio_output_zonos]
enabled = true
endpoint = "http://127.0.0.1:8093"

[plugin.audio_output_player]
enabled = true

[plugin.connector_calendar]
enabled = true

[voice.doktor]
enabled = true
mcp_servers = ["fixture"]

[mcp_servers.fixture]
command = "not-a-real-process"

[cli]
allowlist = ["echo"]
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_run_config_with_voice(config_dir: Path, *, voice_name: str) -> None:
    _write_run_config(config_dir)
    config_path = config_dir / "config.toml"
    original = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        original.replace("[voice.doktor]", f"[voice.{voice_name}]"),
        encoding="utf-8",
    )


def _dependencies(captures: RecordingCaptureFactory, calendars: CalendarFactory) -> RuntimeDependencies:
    return RuntimeDependencies(
        shared={"vad": QuietVad(), "capture_factory": captures},
        calendar_factory=calendars,
    )


def test_run_owner_reports_actionable_calendar_provider_unavailability_without_factory(tmp_path: Path) -> None:
    # Given: the live config enables calendar but production has no provider boundary configured.
    _write_run_config(tmp_path)
    captures = RecordingCaptureFactory()
    dependencies = RuntimeDependencies(
        shared={"vad": QuietVad(), "capture_factory": captures},
    )

    # When: the run owner assembles the configured production graph.
    with pytest.raises(EventRuntimeConfigurationError) as failure:
        build_runtime_owner(load_config(config_dir=tmp_path), dependencies=dependencies)

    # Then: the failure identifies provider unavailability and the concrete credential remediation.
    assert failure.value.field == "plugin.connector_calendar"
    assert "Google Calendar provider is unavailable" in failure.value.reason
    assert "credentials are missing" in failure.value.reason
    assert "google-calendar-credentials.json" in failure.value.reason


@pytest.mark.asyncio
async def test_run_owner_exposes_typed_audio_configuration_seam(tmp_path: Path) -> None:
    # Given: a production runtime configured with microphone and speaker devices.
    _write_run_config(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "[plugin.audio_output_player]\nenabled = true",
            "[plugin.audio_output_player]\nenabled = true\ndevice = 'fixture-speaker'",
        ),
        encoding="utf-8",
    )
    captures = RecordingCaptureFactory()
    assembly = build_runtime_owner(load_config(config_dir=tmp_path), dependencies=_dependencies(captures, CalendarFactory()))

    # When: the TUI runtime seam is queried and updated.
    configurations = {item.plugin: item for item in assembly.plugin_configurations}
    await assembly.configure_plugin(
        "audio_input_mic",
        TuiPluginConfiguration(plugin="audio_input_mic", microphone="updated-mic"),
    )

    # Then: typed controls expose both audio endpoints without starting or rebuilding audio plugins.
    assert configurations["audio_input_mic"].microphone == "fixture-input"
    assert configurations["audio_output_player"].speaker == "fixture-speaker"
    updated = assembly.plugin_configuration("audio_input_mic")
    assert updated is not None
    assert updated.microphone == "updated-mic"


@pytest.mark.asyncio
async def test_run_owner_composes_starts_and_stops_configured_components(tmp_path: Path) -> None:
    # Given: an explicitly authorized MCP grant and every run-mode owner configured.
    _write_run_config(tmp_path)
    captures = RecordingCaptureFactory()
    calendars = CalendarFactory()
    assembly = build_runtime_owner(load_config(config_dir=tmp_path), dependencies=_dependencies(captures, calendars))

    try:
        # When: the production run owner starts its single lifecycle.
        await assembly.start()
        tools = {tool.name for tool in await assembly.mcp_servers[0].fastmcp.list_tools()}

        # Then: the live graph owns calendar, CLI, backlog, workflow, authorized MCP, and hot reload.
        assert isinstance(assembly, RuntimeOwner)
        assert {
            "connector_calendar",
            "connector_cli",
            "backlog",
            "workflow_engine",
            "audio_input_mic",
            "audio_output_player",
        } <= {plugin.name for plugin in assembly.manager.get_plugins()}
        assert len(assembly.mcp_servers) == 1
        assert "backlog_add" in tools
        assert assembly.hot_reload_controller is not None
        assert assembly.is_started
    finally:
        await assembly.stop()

    assert calendars.connector is not None
    assert not calendars.connector.enabled
    assert all(capture.closed for capture in captures.captures)
    assert not assembly.is_started


@pytest.mark.asyncio
async def test_run_owner_reconciles_configured_voice_subscribers_after_reload(tmp_path: Path) -> None:
    # Given: a running owner whose initial configuration enables only Doktor.
    _write_run_config_with_voice(tmp_path, voice_name="doktor")
    captures = RecordingCaptureFactory()
    calendars = CalendarFactory()
    assembly = build_runtime_owner(load_config(config_dir=tmp_path), dependencies=_dependencies(captures, calendars))

    try:
        await assembly.start()
        controller = assembly.hot_reload_controller
        assert controller is not None

        # When: the configured voice definition is changed from Doktor to Jane.
        _write_run_config_with_voice(tmp_path, voice_name="jane")
        await controller.handle_change(tmp_path / "config.toml")

        # Then: the existing manager now routes generate only to the discovered Jane instance.
        generate_registration = next(
            registration
            for registration in assembly.manager.get_event_registrations()
            if registration.name == "generate"
        )
        assert "jane" in generate_registration.receivers
        assert "doktor" not in generate_registration.receivers
        assert "doktor" not in {
            plugin.name for plugin in assembly.manager.get_plugins() if plugin.enabled
        }
    finally:
        await assembly.stop()


@pytest.mark.asyncio
async def test_run_owner_start_failure_cleans_each_previously_owned_component(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a complete run graph whose final hot-reload component cannot start.
    _write_run_config(tmp_path)
    captures = RecordingCaptureFactory()
    calendars = CalendarFactory()
    assembly = build_runtime_owner(load_config(config_dir=tmp_path), dependencies=_dependencies(captures, calendars))

    async def fail_start(controller: HotReloadController) -> None:
        del controller
        raise ReloadStartFailure()

    _ = monkeypatch.setattr(HotReloadController, "start", fail_start)

    # When: startup reaches the failing run-mode boundary.
    with pytest.raises(ReloadStartFailure):
        await assembly.start()

    # Then: the failure leaves no active plugin, MCP observer, provider, or capture resource behind.
    assert calendars.connector is not None
    assert not calendars.connector.enabled
    assert all(capture.closed for capture in captures.captures)
    assert not any(plugin.enabled for plugin in assembly.manager.get_plugins())
    assert not assembly.is_started


@pytest.mark.asyncio
async def test_cancelling_run_event_runtime_closes_the_owned_configured_calendar(tmp_path: Path) -> None:
    # Given: a live run whose audio capture signals that the complete owner is running.
    _write_run_config(tmp_path)
    captures = RecordingCaptureFactory()
    calendars = CalendarFactory()
    task = asyncio.create_task(
        run_event_runtime(load_config(config_dir=tmp_path), dependencies=_dependencies(captures, calendars))
    )

    # When: the active run task is cancelled like an interrupted CLI session.
    _ = await asyncio.wait_for(captures.started.wait(), timeout=1)
    _ = task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Then: cancellation reaches the shared owner and releases its calendar and capture boundaries.
    assert calendars.connector is not None
    assert not calendars.connector.enabled
    assert all(capture.closed for capture in captures.captures)
