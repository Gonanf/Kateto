from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kateto.core.config import PluginSettings, load_config
from kateto.core.event import AudioOutput, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.audio_output.piper_tts_plugin import PiperTTSAudioOutput
from kateto.providers.piper import PiperProvider, PiperVoiceNotAvailableError
from kateto.voices.prompt_blocks import get_agent_prompt_block


# --- config resolution -----------------------------------------------------


def test_voice_folder_config_with_piper(tmp_path: Path):
    # Given: a voice directory with tts_provider = "piper" and per-voice fields
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("""\
[kateto]
debug = false

[cli]
allowlist = ["ls"]
""", encoding="utf-8")

    custom_voice_dir = config_dir / "voices" / "jane"
    custom_voice_dir.mkdir(parents=True)
    (custom_voice_dir / "config.toml").write_text("""\
enabled = true
dept = "fun"
tts_provider = "piper"
piper_voice = "es_AR-daniela-high"
piper_length_scale = 0.9
piper_speaker_id = 2
""", encoding="utf-8")

    # When: loading config
    loaded = load_config(config_dir=config_dir)

    # Then: piper fields resolve from the voice folder, edge_tts absent
    jane = loaded.settings.voice["jane"]
    assert jane.tts_provider == "piper"
    assert jane.get("piper_voice") == "es_AR-daniela-high"
    assert jane.get("piper_length_scale") == 0.9
    assert jane.get("piper_speaker_id") == 2
    assert jane.get("edge_tts_voice") is None


def test_piper_plugin_defaults_without_voice_map():
    # Given: plugin-level defaults, no per-voice map
    settings = PluginSettings(default_voice="es_AR-daniela-high")
    plugin = PiperTTSAudioOutput(settings, provider=MagicMock())

    # Then: defaults apply
    assert plugin._default_voice == "es_AR-daniela-high"
    assert plugin._default_length_scale == 1.0
    assert plugin._default_speaker_id is None


def test_get_agent_prompt_block_piper():
    block = get_agent_prompt_block("piper")
    assert block is not None
    assert "Piper TTS" in block
    assert get_agent_prompt_block("PIPER") == block


# --- plugin behavior (no real model) ---------------------------------------


class _ChunkingProvider:
    """Fake provider: streams 3 PCM chunks then lets the plugin close the lane."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float, int | None]] = []

    async def stream_sentence(self, sentence, *, voice, length_scale=1.0, speaker_id=None):
        self.calls.append((voice, length_scale, speaker_id))
        for _ in range(3):
            yield AudioOutput(
                samples=b"\x01\x00" * 512,
                sample_rate=22_050,
                channels=1,
                format="pcm_s16le",
                voice_id=sentence.voice_id,
                sequence=len(self.calls),
                final=False,
                text=sentence.text,
            )


class _RaisingProvider:
    async def stream_sentence(self, sentence, *, voice, length_scale=1.0, speaker_id=None):
        raise PiperVoiceNotAvailableError("piper-tts is not installed")
        yield  # pragma: no cover - async generator so the raise surfaces on iteration


def _make_manager(plugin):
    manager = PluginManager()
    manager.register_plugin(plugin)
    emitted = []

    def observer(envelope):
        if envelope.name == "audio_output":
            emitted.append(envelope.data)

    manager.add_event_observer(observer)
    return manager, emitted


@pytest.mark.asyncio
async def test_piper_plugin_resolves_per_voice_params_and_emits():
    # Given: a plugin wired with Jane's per-voice piper config
    provider = _ChunkingProvider()
    plugin = PiperTTSAudioOutput(
        PluginSettings(),
        provider=provider,
        voice_map={
            "jane": {
                "piper_voice": "es_AR-daniela-high",
                "piper_length_scale": "0.9",
                "piper_speaker_id": "3",
            }
        },
    )
    manager, emitted = _make_manager(plugin)
    await manager.enable_plugin(plugin)

    # When: a text chunk arrives for Jane
    chunk = TextChunk(text="Hola Kateto, esto es una prueba.", voice_id="jane", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: the provider was called with Jane's piper voice + params
    assert provider.calls == [("es_AR-daniela-high", 0.9, 3)]

    # And PCM audio_output events were emitted, ending with the lane-closing final
    assert len(emitted) > 0
    assert any(a.samples for a in emitted)
    assert emitted[-1].final
    assert all(a.sample_rate == 22_050 for a in emitted)
    await manager.close()


@pytest.mark.asyncio
async def test_piper_plugin_degrades_cleanly_when_dependency_missing():
    # Given: a provider that cannot find piper-tts
    plugin = PiperTTSAudioOutput(
        PluginSettings(),
        provider=_RaisingProvider(),
        voice_map={"jane": {"piper_voice": "es_AR-daniela-high"}},
    )
    manager, emitted = _make_manager(plugin)
    await manager.enable_plugin(plugin)

    # When: synthesis is attempted
    chunk = TextChunk(text="Hola Kateto.", voice_id="jane", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: no exception escapes, the lane is closed with a final, runtime stays up
    assert plugin.enabled is True
    assert emitted, "expected at least the lane-closing final"
    assert emitted[-1].final
    assert all(a.samples == b"" for a in emitted)
    await manager.close()


# --- provider degradation ---------------------------------------------------


@pytest.mark.asyncio
async def test_piper_provider_raises_when_dependency_missing(tmp_path: Path):
    provider = PiperProvider(PluginSettings(download_dir=str(tmp_path)))
    # Model file present so resolution reaches the lazy piper import.
    (provider._download_dir / "es_AR-daniela-high.onnx").write_bytes(b"fake")
    # Force the lazy import to fail regardless of the environment.
    with patch.dict(sys.modules, {"piper": None, "piper.config": None}):
        with pytest.raises(PiperVoiceNotAvailableError, match="piper-tts is not installed"):
            async for _ in provider.stream_sentence(
                TextChunk(text="hola", voice_id="jane", sequence=0), voice="es_AR-daniela-high"
            ):
                pass


@pytest.mark.asyncio
async def test_piper_provider_raises_when_model_missing(tmp_path: Path):
    # Given: a configured download_dir with no models in it
    provider = PiperProvider(PluginSettings(download_dir=str(tmp_path)))

    # When/Then: a clear error names the model path and the download command
    with pytest.raises(PiperVoiceNotAvailableError, match="not found"):
        async for _ in provider.stream_sentence(
            TextChunk(text="hola", voice_id="jane", sequence=0), voice="es_AR-daniela-high"
        ):
            pass


# --- provider streaming with a fake piper module ----------------------------


class _FakeAudioChunk:
    sample_rate = 22_050
    audio_int16_bytes = b"\x01\x00" * 512


class _FakeSynthesisConfig:
    def __init__(self, speaker_id=None, length_scale=None) -> None:
        self.speaker_id = speaker_id
        self.length_scale = length_scale


class _FakeVoice:
    config = types.SimpleNamespace(sample_rate=22_050)
    load_count = 0

    @classmethod
    def load(cls, model_path, config_path=None, use_cuda=False):
        cls.load_count += 1
        return cls()

    def synthesize(self, text, syn_config=None):
        assert syn_config is not None
        assert syn_config.speaker_id == 2
        assert syn_config.length_scale == 0.9
        for _ in range(3):
            yield _FakeAudioChunk()


@pytest.fixture()
def fake_piper_modules():
    fake_piper = types.ModuleType("piper")
    fake_piper_config = types.ModuleType("piper.config")
    fake_piper_config.SynthesisConfig = _FakeSynthesisConfig
    return {"piper": fake_piper, "piper.config": fake_piper_config}


@pytest.mark.asyncio
async def test_piper_provider_streams_pcm_and_caches_voice(tmp_path: Path, fake_piper_modules):
    # Given: a voice model file and a piper-tts stand-in
    provider = PiperProvider(PluginSettings(download_dir=str(tmp_path)))
    (provider._download_dir / "es_AR-daniela-high.onnx").write_bytes(b"fake")
    provider._piper_voice_cls = _FakeVoice
    _FakeVoice.load_count = 0

    sentence = TextChunk(text="Hola Kateto.", voice_id="jane", sequence=0)

    # When: synthesizing a short phrase with per-voice params
    with patch.dict(sys.modules, fake_piper_modules):
        outputs: list[AudioOutput] = []
        async for out in provider.stream_sentence(
            sentence, voice="es_AR-daniela-high", length_scale=0.9, speaker_id=2
        ):
            outputs.append(out)

    # Then: 3 PCM chunks streamed + a closing final, all at the voice's rate
    assert len(outputs) == 4
    assert all(o.samples for o in outputs[:3])
    assert outputs[-1].final
    assert all(o.sample_rate == 22_050 for o in outputs)
    assert all(o.format == "pcm_s16le" for o in outputs)

    # And a second synthesis reuses the cached voice (load once per process)
    with patch.dict(sys.modules, fake_piper_modules):
        async for _ in provider.stream_sentence(
            sentence, voice="es_AR-daniela-high", length_scale=0.9, speaker_id=2
        ):
            pass
    assert _FakeVoice.load_count == 1


# --- integration (skipped without piper-tts / model) ------------------------


@pytest.mark.asyncio
async def test_piper_integration_synthesizes_short_phrase():
    provider = PiperProvider(PluginSettings())
    try:
        provider._piper()
    except PiperVoiceNotAvailableError as exc:
        pytest.skip(f"piper-tts not installed: {exc}")
    if not (provider._download_dir / "es_AR-daniela-high.onnx").is_file():
        pytest.skip("voice model es_AR-daniela-high not downloaded (no network in tests)")

    chunks: list[AudioOutput] = []
    async for out in provider.stream_sentence(
        TextChunk(text="Hola Kateto.", voice_id="jane", sequence=0), voice="es_AR-daniela-high"
    ):
        chunks.append(out)

    assert chunks, "expected at least one audio chunk"
    assert any(c.samples for c in chunks), "expected non-empty PCM"
    assert chunks[-1].final