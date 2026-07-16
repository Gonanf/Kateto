from __future__ import annotations

import random
from collections.abc import AsyncIterator
from importlib import import_module as standard_import_module
from pathlib import Path
from types import ModuleType

import pytest

import kateto.core.discovery as discovery

from kateto.core.config import load_config
from kateto.core.discovery import DiscoveryContext, DiscoveryDependencies, discover_plugins
from kateto.core.event import AudioData, AudioOutput, Classification, GenerateData, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.audio_input.base import AudioInputConfig, CaptureCallback
from kateto.plugins.executor.todo_list import TodoListExecutor
from kateto.tests.conversation_support import (
    FixtureClassifier,
    FixtureTranscriber,
    StreamingFixtureProvider,
    write_references,
)


class QuietVad:
    def is_speech(self, samples: bytes) -> bool:
        del samples
        return False


class RecordingCapture:
    started: bool
    stopped: bool
    closed: bool

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class RecordingCaptureFactory:
    def __init__(self) -> None:
        self.requests: list[AudioInputConfig] = []
        self.callbacks: list[CaptureCallback] = []
        self.captures: list[RecordingCapture] = []

    def create(self, config: AudioInputConfig, callback: CaptureCallback) -> RecordingCapture:
        self.requests.append(config)
        self.callbacks.append(callback)
        capture = RecordingCapture()
        self.captures.append(capture)
        return capture


class RecordingOutputStream:
    started: bool
    stopped: bool
    closed: bool

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.closed = False
        self.writes: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def write(self, data: bytes) -> None:
        self.writes.append(data)


class RecordingOutputFactory:
    def __init__(self) -> None:
        self.streams: list[RecordingOutputStream] = []

    def create(
        self,
        *,
        device: str | None,
        sample_rate: int,
        channels: int,
    ) -> RecordingOutputStream:
        del device, sample_rate, channels
        stream = RecordingOutputStream()
        self.streams.append(stream)
        return stream


class FixturePcmProvider:
    entered: bool
    closed: bool

    def __init__(self) -> None:
        self.entered = False
        self.closed = False

    async def __aenter__(self) -> FixturePcmProvider:
        self.entered = True
        return self

    async def aclose(self) -> None:
        self.closed = True

    def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        return self._stream(sentence, voice_id)

    async def _stream(self, sentence: TextChunk, voice_id: str) -> AsyncIterator[AudioOutput]:
        yield AudioOutput(
            samples=b"\x01\x00",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice_id,
            sequence=sentence.sequence,
        )
        yield AudioOutput(
            samples=b"",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice_id,
            sequence=sentence.sequence + 1,
            final=True,
        )


def _write_discovery_config(config_dir: Path) -> None:
    _ = (config_dir / "config.toml").write_text(
        """
[kateto]

[plugin.audio_output_player]
enabled = true

[plugin.executor_classifier]
enabled = true
model_endpoint = "http://127.0.0.1:8091"
model = "fixture-classifier"

[plugin.audio_input_mic]
enabled = true
sample_rate = 16000
silence_timeout = 0.1
vad_model = "silero"

[plugin.voice_llm]
enabled = true
endpoint = "http://127.0.0.1:8092/v1"
model = "fixture-voice"

[plugin.executor_todo_list]
enabled = true

[plugin.audio_output_zonos]
enabled = true
endpoint = "http://127.0.0.1:8093"

[plugin.audio_processor_whisper]
enabled = true
endpoint = "http://127.0.0.1:8090"

[plugin.executor_interrupt]
enabled = true

[voice.doktor]
enabled = true

[cli]
allowlist = ["echo"]
""".strip()
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_discovery_routes_shuffled_configured_plugins_through_initialized_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: shuffled config definitions and typed fixture dependencies at every external boundary.
    _write_discovery_config(tmp_path)
    write_references(tmp_path)
    imported_modules: list[str] = []

    def record_import(module_name: str) -> ModuleType:
        imported_modules.append(module_name)
        return standard_import_module(module_name)

    _ = monkeypatch.setattr(discovery, "import_module", record_import)
    captures = RecordingCaptureFactory()
    outputs = RecordingOutputFactory()
    pcm = FixturePcmProvider()
    context = DiscoveryContext(
        config=load_config(config_dir=tmp_path),
        dependencies=DiscoveryDependencies(
            vad=QuietVad(),
            capture_factory=captures,
            player_factory=outputs,
            whisper_provider=FixtureTranscriber(("plan tomorrow standup",)),
            classifier=FixtureClassifier(Classification.EXECUTE),
            voice_provider=StreamingFixtureProvider(),
            zonos_provider=pcm,
        ),
    )

    # When: discovery imports only enabled configured modules, then the set is enabled in a shuffled order.
    registry = discover_plugins(context)
    manager = PluginManager()
    ordered_plugins = tuple(sorted(registry.plugins, key=lambda plugin: plugin.name))
    shuffled_plugins = tuple(random.Random(17).sample(ordered_plugins, k=len(ordered_plugins)))
    assert [plugin.name for plugin in shuffled_plugins] != [plugin.name for plugin in ordered_plugins]
    for plugin in shuffled_plugins:
        await manager.enable_plugin(plugin)
    try:
        _ = await manager.emit(
            "audio_chunk",
            AudioData(samples=b"\x01\x00", format="pcm_s16le"),
            source="fixture",
        )
        await manager.wait_for_idle()

        # Then: initialized handler contracts route the whole event flow without a pipeline ordering contract.
        registrations = {registration.name: registration for registration in manager.get_event_registrations()}
        event_names = [event.name for event in manager.get_events()]
        generate = next(event for event in manager.get_events() if event.name == "generate")
        assert {plugin.name for plugin in registry.plugins} == {
            "audio_input_mic",
            "audio_output_player",
            "audio_output_zonos",
            "audio_processor_whisper",
            "backlog",
            "connector_cli",
            "doktor",
            "executor_classifier",
            "executor_interrupt",
            "executor_todo_list",
        }
        todo_executor = next(plugin for plugin in registry.plugins if isinstance(plugin, TodoListExecutor))
        assert isinstance(todo_executor, TodoListExecutor)
        assert todo_executor._store.voice == "shared"
        assert {plugin.name for plugin in registry.input_plugins} == {"audio_input_mic"}
        assert {
            "kateto.plugins.audio_input.mic",
            "kateto.plugins.audio_output.player",
            "kateto.plugins.audio_output.zonos",
            "kateto.plugins.audio_processor.whisper",
            "kateto.plugins.connector.cli",
            "kateto.plugins.executor.classifier",
            "kateto.plugins.executor.interrupt",
            "kateto.plugins.executor.todo_list",
            "kateto.plugins.work.backlog",
            "kateto.voices.doktor",
        } == set(imported_modules)
        assert registrations["audio_chunk"].contract is AudioData
        assert set(registrations["generate"].receivers) == {"doktor"}
        assert {"audio_input_mic", "audio_output_player"} <= set(registrations["audio_output"].receivers)
        assert all(name in event_names for name in ("transcription", "classification", "generate", "text_chunk", "audio_output"))
        assert generate.data == GenerateData(prompt="plan tomorrow standup")
        assert generate.target is None
        assert outputs.streams[0].writes == [b"\x01\x00"]
    finally:
        await manager.close()

    assert pcm.entered and pcm.closed
    assert all(capture.started and capture.stopped and capture.closed for capture in captures.captures)
    assert all(stream.started and stream.stopped and stream.closed for stream in outputs.streams)
