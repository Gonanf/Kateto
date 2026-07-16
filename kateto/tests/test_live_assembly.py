from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core.config import load_config
from kateto.core.event import AudioOutput, TodoItemData
from kateto.live import LiveDependencies, build_live_conversation
from kateto.plugins.audio_input.base import (
    AudioDeviceError,
    AudioInputConfig,
    CaptureCallback,
    SAMPLE_RATE,
    SileroVad,
)
from kateto.plugins.audio_input.mic import MicrophoneAudioInput
from kateto.plugins.audio_input.silero import SileroModel, SileroModelLoader


class QuietVad:
    def is_speech(self, samples: bytes) -> bool:
        return bool(samples) and False


class RecordingSileroModel:
    def __init__(self, probability: float) -> None:
        self._probability = probability
        self.calls: list[tuple[bytes, int]] = []

    def speech_probability(self, samples: bytes, sample_rate: int) -> float:
        self.calls.append((samples, sample_rate))
        return self._probability


class RecordingSileroModelLoader:
    def __init__(self, model: SileroModel) -> None:
        self._model = model
        self.load_count = 0

    def load_model(self) -> SileroModel:
        self.load_count += 1
        return self._model


class RecordingCapture:
    def __init__(self, *, fail_on_start: bool = False) -> None:
        self.fail_on_start = fail_on_start
        self.started: bool = False
        self.stopped: bool = False
        self.closed: bool = False

    def start(self) -> None:
        if self.fail_on_start:
            raise AudioDeviceError(source="microphone", device="default", reason="fixture failure")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class RecordingCaptureFactory:
    def __init__(self, *, fail_on_start: bool = False) -> None:
        self.fail_on_start = fail_on_start
        self.requests: list[AudioInputConfig] = []
        self.callbacks: list[CaptureCallback] = []
        self.captures: list[RecordingCapture] = []

    def create(self, config: AudioInputConfig, callback: CaptureCallback) -> RecordingCapture:
        self.requests.append(config)
        self.callbacks.append(callback)
        capture = RecordingCapture(fail_on_start=self.fail_on_start)
        self.captures.append(capture)
        return capture


class RecordingOutputStream:
    def __init__(self) -> None:
        self.started: bool = False
        self.stopped: bool = False
        self.closed: bool = False
        self.writes: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def write(self, data: bytes) -> object:
        self.writes.append(data)
        return None


class RecordingOutputFactory:
    def __init__(self) -> None:
        self.requests: list[tuple[str | None, int, int]] = []
        self.streams: list[RecordingOutputStream] = []

    def create(
        self,
        *,
        device: str | None,
        sample_rate: int,
        channels: int,
    ) -> RecordingOutputStream:
        self.requests.append((device, sample_rate, channels))
        stream = RecordingOutputStream()
        self.streams.append(stream)
        return stream


def write_live_config(config_dir: Path) -> None:
    _ = (config_dir / "config.toml").write_text(
        """
[kateto]

[plugin.audio_input_mic]
enabled = true
device = "default"
sample_rate = 16000
silence_timeout = 0.1
vad_model = "silero"

[plugin.audio_processor_whisper]
enabled = true
endpoint = "http://127.0.0.1:8090"

[plugin.executor_classifier]
enabled = true
model_endpoint = "http://127.0.0.1:8091"
model = "classifier"

[plugin.voice_llm]
enabled = true
endpoint = "http://127.0.0.1:8092/v1"
model = "voice"

[plugin.audio_output_zonos]
enabled = true
endpoint = "http://127.0.0.1:8093"

[plugin.audio_output_player]
enabled = true
device = "Fixture Output"

[plugin.executor_interrupt]
enabled = true

[plugin.executor_todo_list]
enabled = true

[voice.jane]
enabled = true

[voice.doktor]
enabled = true

[voice.conquest]
enabled = true

[cli]
allowlist = ["echo"]
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_default_live_assembly_loads_and_invokes_injected_silero_model(tmp_path: Path) -> None:
    # Given: live configuration explicitly selects Silero and a weight-free model loader.
    write_live_config(tmp_path)
    model = RecordingSileroModel(probability=0.9)
    loader: SileroModelLoader = RecordingSileroModelLoader(model)

    # When: the production live assembly resolves its default VAD and processes PCM.
    assembly = build_live_conversation(
        load_config(config_dir=tmp_path),
        silero_model_loader=loader,
    )
    microphone = next(
        plugin
        for plugin in assembly._input_plugins
        if isinstance(plugin, MicrophoneAudioInput)
    )
    detected_speech = microphone._vad.is_speech(b"\x01\x00" * 512)

    # Then: assembly installs Silero VAD and delegates the configured PCM to its model.
    assert isinstance(microphone._vad, SileroVad)
    assert detected_speech
    assert loader.load_count == 1
    assert model.calls == [(b"\x01\x00" * 512, SAMPLE_RATE)]


@pytest.mark.asyncio
async def test_configured_live_assembly_starts_and_stops_production_plugins(tmp_path: Path) -> None:
    # Given: a complete live configuration and injected hardware-only capture/output seams.
    write_live_config(tmp_path)
    capture_factory = RecordingCaptureFactory()
    output_factory = RecordingOutputFactory()
    assembly = build_live_conversation(
        load_config(config_dir=tmp_path),
        dependencies=LiveDependencies(
            vad=QuietVad(),
            capture_factory=capture_factory,
            player_factory=output_factory,
        ),
    )

    # When: the configured production assembly starts, receives PCM, and stops.
    await assembly.start()
    _ = await assembly.manager.emit(
        "audio_output",
        AudioOutput(samples=b"\x01\x00", sample_rate=24_000, channels=1, format="pcm_s16le"),
        source="audio_output_zonos",
    )
    await assembly.manager.wait_for_idle()
    await assembly.stop()

    # Then: all configured production boundaries own and release their resources without fixture plugins.
    assert {plugin.name for plugin in assembly.manager.get_plugins()} == {
        "audio_input_mic",
        "audio_processor_whisper",
        "executor_interrupt",
        "executor_classifier",
        "executor_todo_list",
        "connector_cli",
        "backlog",
        "jane",
        "doktor",
        "conquest",
        "audio_output_zonos",
        "audio_output_player",
    }
    assert all("fixture" not in type(plugin).__module__ for plugin in assembly.manager.get_plugins())
    assert capture_factory.requests[0].device == "default"
    assert all(capture.started and capture.stopped and capture.closed for capture in capture_factory.captures)
    assert output_factory.requests == [("Fixture Output", 24_000, 1)]
    assert all(stream.started and stream.stopped and stream.closed for stream in output_factory.streams)
    assert all(provider.is_closed for provider in assembly.providers)
    assert not any(plugin.enabled for plugin in assembly.manager.get_plugins())


@pytest.mark.asyncio
async def test_live_assembly_persists_completed_todo_through_cli_backlog_owner(tmp_path: Path) -> None:
    # Given: a configured non-fixture live assembly with a restricted CLI allowlist.
    write_live_config(tmp_path)
    assembly = build_live_conversation(
        load_config(config_dir=tmp_path),
        dependencies=LiveDependencies(
            vad=QuietVad(),
            capture_factory=RecordingCaptureFactory(),
            player_factory=RecordingOutputFactory(),
        ),
    )

    try:
        await assembly.start()

        # When: the live TODO completion boundary emits a completed item.
        await assembly.manager.emit(
            "todo_completed",
            TodoItemData(voice="doktor", task="tomorrow standup", completed=True),
            source="executor_todo_list",
        )
        await assembly.manager.wait_for_idle()

        # Then: the configured live owner persists the CLI connector's backlog action canonically.
        backlog = (tmp_path / "product_backlog.json").read_text(encoding="utf-8")
        assert '"title": "tomorrow standup"' in backlog
        assert '"status": "Done"' in backlog
        assert {plugin.name for plugin in assembly.manager.get_plugins()} >= {
            "connector_cli",
            "backlog",
        }
    finally:
        await assembly.stop()


@pytest.mark.asyncio
async def test_live_start_failure_closes_opened_resources_and_workers(tmp_path: Path) -> None:
    # Given: providers and output plugins can open, but deterministic capture startup fails.
    write_live_config(tmp_path)
    capture_factory = RecordingCaptureFactory(fail_on_start=True)
    assembly = build_live_conversation(
        load_config(config_dir=tmp_path),
        dependencies=LiveDependencies(
            vad=QuietVad(),
            capture_factory=capture_factory,
            player_factory=RecordingOutputFactory(),
        ),
    )

    # When: live startup reaches the failing capture boundary.
    with pytest.raises(AudioDeviceError, match="fixture failure"):
        await assembly.start()

    # Then: every opened boundary is closed and no plugin worker remains active.
    assert all(capture.closed for capture in capture_factory.captures)
    assert all(provider.is_closed for provider in assembly.providers)
    assert not any(plugin.enabled for plugin in assembly.manager.get_plugins())
    assert all(plugin._worker is None or plugin._worker.done() for plugin in assembly.manager.get_plugins())
