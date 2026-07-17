from __future__ import annotations

import random
from importlib import import_module as standard_import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import kateto.core.discovery as discovery

from kateto.core.config import load_config
from kateto.core.discovery import DiscoveryContext, discover_plugins
from kateto.core.event import AudioData
from kateto.core.manager import PluginManager
from kateto.tests.conversation_support import write_references


class QuietVad:
    def is_speech(self, samples: bytes) -> bool:
        del samples
        return False


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
    _write_discovery_config(tmp_path)
    write_references(tmp_path)

    def record_import(module_name: str) -> ModuleType:
        return standard_import_module(module_name)

    _ = monkeypatch.setattr(discovery, "import_module", record_import)

    fixture_transcriber = _FakeTranscriber()
    fixture_classifier = _FakeClassifier()

    monkeypatch.setattr("kateto.providers.WhisperProvider", lambda s: fixture_transcriber)
    monkeypatch.setattr("kateto.providers.ClassifierProvider", lambda s: fixture_classifier)
    monkeypatch.setattr("kateto.providers.ZonosProvider", lambda s: _FakePcmProvider())

    context = DiscoveryContext(
        config=load_config(config_dir=tmp_path),
        shared={"vad": QuietVad()},
    )

    registry = discover_plugins(context)
    manager = PluginManager()

    discovered_names = {plugin.name for plugin in registry.plugins}
    assert len(discovered_names) == len(registry.plugins)
    assert discovered_names >= {
        "executor_classifier", "executor_interrupt", "executor_todo_list",
        "connector_cli", "backlog",
    }

    ordered_plugins = tuple(sorted(registry.plugins, key=lambda p: p.name))
    shuffled = tuple(random.Random(17).sample(ordered_plugins, k=len(ordered_plugins)))
    assert [p.name for p in shuffled] != [p.name for p in ordered_plugins]

    for plugin in shuffled:
        await manager.enable_plugin(plugin)
    try:
        registrations = {r.name: r for r in manager.get_event_registrations()}
        assert registrations["audio_chunk"].contract is AudioData

        if "audio_input_mic" in discovered_names:
            _ = await manager.emit(
                "audio_chunk",
                AudioData(samples=b"\x01\x00", format="pcm_s16le"),
                source="fixture",
            )
            await manager.wait_for_idle()
            assert "audio_input_mic" <= set(registrations["audio_output"].receivers)
    finally:
        await manager.close()


class _FakeTranscriber:
    async def __aenter__(self):
        return self

    async def aclose(self):
        pass

    async def transcribe(self, audio):
        from kateto.core.event import TranscriptionData
        return TranscriptionData(text="fixture")


class _FakeClassifier:
    async def __aenter__(self):
        return self

    async def aclose(self):
        pass

    async def classify(self, text):
        from kateto.core.event import ClassificationData, Classification
        return ClassificationData(text=text, category=Classification.EXECUTE)


class _FakePcmProvider:
    async def __aenter__(self):
        return self

    async def aclose(self):
        pass

    async def stream_sentence(self, sentence, *, voice_id):
        return
        yield
