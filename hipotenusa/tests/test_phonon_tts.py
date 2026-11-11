from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from hipotenusa.core.config import PluginSettings
from hipotenusa.core.event import AudioOutput, TextChunk
from hipotenusa.core.manager import PluginManager
from hipotenusa.plugins.audio_output.phonon_tts_plugin import (
    DEFAULT_MODEL,
    PhononProvider,
    PhononTTSAudioOutput,
    PhononVoiceNotAvailableError,
    _pcm16,
)


# --- defaults & config -----------------------------------------------------


def test_phonon_plugin_defaults_without_voice_map():
    # Given: plugin-level defaults, no per-voice map
    plugin = PhononTTSAudioOutput(PluginSettings(default_voice="Iker"))

    # Then: the plugin default voice applies; absent config leaves it to ptts
    assert plugin._default_voice == "Iker"
    assert PhononTTSAudioOutput(PluginSettings())._default_voice is None


def test_phonon_provider_reads_model_lang_quant_from_settings():
    # Given: a plugin section naming the checkpoint, language and quant
    provider = PhononProvider(
        PluginSettings(model="hf://gradium/phonon-40m-multilingual", lang="es", quant="q8")
    )

    # Then: the runtime is configured from config, not hardcoded
    assert provider._model == "hf://gradium/phonon-40m-multilingual"
    assert provider._lang == "es"
    assert provider._quant == "q8"

    # And defaults point at the Spanish 40m checkpoint
    assert PhononProvider(PluginSettings())._model == DEFAULT_MODEL


def test_pcm16_converts_float32_to_signed_16bit_le():
    # Given: float32 frames in [-1, 1]
    chunk = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)

    # When: encoding to the player lane format
    raw = _pcm16(chunk)

    # Then: little-endian int16, full scale clipped
    assert raw[:2] == b"\x00\x00"
    samples = np.frombuffer(raw, dtype="<i2")
    assert samples[3] == 32767
    assert samples[4] == -32767
    assert abs(int(samples[1]) - 16383) <= 1 and abs(int(samples[2]) + 16383) <= 1


# --- plugin behavior (no real model) ---------------------------------------


class _ChunkingProvider:
    """Fake provider: streams 3 PCM chunks at the Phonon rate."""

    def __init__(self) -> None:
        self.calls: list[str | None] = []

    async def stream_sentence(self, sentence, *, voice=None):
        self.calls.append(voice)
        for _ in range(3):
            yield AudioOutput(
                samples=b"\x01\x00" * 512,
                sample_rate=24_000,
                channels=1,
                format="pcm_s16le",
                voice_id=sentence.voice_id,
                sequence=0,
                final=False,
                text=sentence.text,
            )


class _RaisingProvider:
    async def stream_sentence(self, sentence, *, voice=None):
        raise PhononVoiceNotAvailableError("ptts is not installed")
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
async def test_phonon_plugin_resolves_per_voice_param_and_emits():
    # Given: a plugin wired with Jane's per-voice phonon voice
    provider = _ChunkingProvider()
    plugin = PhononTTSAudioOutput(
        PluginSettings(),
        provider=provider,
        voice_map={"jane": {"phonon_voice": "Iker"}},
    )
    manager, emitted = _make_manager(plugin)
    await manager.enable_plugin(plugin)

    # When: a text chunk arrives for Jane
    chunk = TextChunk(text="Hola Hipotenusa, esto es una prueba.", voice_id="jane", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: the provider got Jane's voice name
    assert provider.calls == ["Iker"]

    # And PCM audio_output events were emitted, ending with the lane-closing final
    assert emitted
    assert any(a.samples for a in emitted)
    assert emitted[-1].final
    assert all(a.sample_rate == 24_000 for a in emitted)
    assert all(a.format == "pcm_s16le" for a in emitted)
    await manager.close()


@pytest.mark.asyncio
async def test_phonon_plugin_degrades_cleanly_when_dependency_missing():
    # Given: a provider that cannot import ptts
    plugin = PhononTTSAudioOutput(
        PluginSettings(),
        provider=_RaisingProvider(),
        voice_map={"jane": {"phonon_voice": "Iker"}},
    )
    manager, emitted = _make_manager(plugin)
    await manager.enable_plugin(plugin)

    # When: synthesis is attempted
    chunk = TextChunk(text="Hola Hipotenusa.", voice_id="jane", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: no exception escapes, the lane is closed with a final, runtime stays up
    assert plugin.enabled is True
    assert emitted, "expected at least the lane-closing final"
    assert emitted[-1].final
    assert all(a.samples == b"" for a in emitted)
    await manager.close()


# --- provider degradation ---------------------------------------------------


@pytest.mark.asyncio
async def test_phonon_provider_raises_when_ptts_missing():
    provider = PhononProvider(PluginSettings())
    # Force the lazy import to fail regardless of the environment.
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "ptts", None)
        with pytest.raises(PhononVoiceNotAvailableError, match="ptts is not installed"):
            async for _ in provider.stream_sentence(
                TextChunk(text="hola", voice_id="jane", sequence=0), voice="Iker"
            ):
                pass


@pytest.mark.asyncio
async def test_phonon_provider_reports_gated_checkpoint_with_hf_token_hint():
    # Given: a ptts stand-in whose TTS() refuses the gated checkpoint
    def _refuse(*args, **kwargs):
        raise RuntimeError("Access denied: gate not accepted")

    fake_ptts = types.SimpleNamespace(TTS=_refuse)
    provider = PhononProvider(PluginSettings(model="hf://gradium/phonon-40m-es"))

    # When/Then: the error names the checkpoint and the HF_TOKEN remedy
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "ptts", fake_ptts)
        with pytest.raises(PhononVoiceNotAvailableError, match="HF_TOKEN"):
            async for _ in provider.stream_sentence(
                TextChunk(text="hola", voice_id="jane", sequence=0), voice="Iker"
            ):
                pass


# --- provider streaming with a fake ptts module ----------------------------


class _FakeStream:
    def __init__(self, chunks) -> None:
        self._chunks = chunks
        self.closed = False

    def __enter__(self):
        return iter(self._chunks)

    def __exit__(self, *exc) -> None:
        self.closed = True


class _FakeTTS:
    sample_rate = 24_000
    instances = 0

    def __init__(self, model, *, lang=None, quant=None, device=None) -> None:
        type(self).instances += 1
        self.model = model
        self.lang = lang
        self.quant = quant
        self.device = device

    def stream(self, text, *, voice=None):
        assert text
        return _FakeStream([np.full(960, 0.25, dtype=np.float32) for _ in range(3)])


@pytest.mark.asyncio
async def test_phonon_provider_streams_int16_pcm_and_caches_model():
    # Given: a ptts stand-in streaming three 80ms float32 frames
    fake_ptts = types.SimpleNamespace(TTS=_FakeTTS)
    provider = PhononProvider(PluginSettings(model="hf://gradium/phonon-40m-es", lang="es", quant="q8"))
    _FakeTTS.instances = 0
    sentence = TextChunk(text="Hola Hipotenusa.", voice_id="jane", sequence=0)

    # When: synthesizing a short phrase
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "ptts", fake_ptts)
        outputs: list[AudioOutput] = []
        async for out in provider.stream_sentence(sentence, voice="Iker"):
            outputs.append(out)

    # Then: 3 int16 PCM frames streamed + a closing final, all at 24kHz mono
    assert len(outputs) == 4
    assert all(o.samples for o in outputs[:3])
    assert all(o.sample_rate == 24_000 and o.channels == 1 for o in outputs)
    assert all(o.format == "pcm_s16le" for o in outputs)
    assert all(len(o.samples) == 960 * 2 for o in outputs[:3])
    assert outputs[-1].final and outputs[-1].samples == b""

    # And the checkpoint was constructed once (cached across sentences)
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(sys.modules, "ptts", fake_ptts)
        async for _ in provider.stream_sentence(sentence, voice="Iker"):
            pass
    assert _FakeTTS.instances == 1


# --- integration (skipped without ptts / model) ----------------------------


@pytest.mark.asyncio
async def test_phonon_integration_synthesizes_short_phrase():
    try:
        import ptts  # noqa: F401, PLC0415
    except ImportError as exc:
        pytest.skip(f"ptts not installed: {exc}")

    provider = PhononProvider(PluginSettings(model=DEFAULT_MODEL))
    try:
        provider._load()
    except PhononVoiceNotAvailableError as exc:
        pytest.skip(f"phonon checkpoint unavailable (gated / no HF_TOKEN / offline): {exc}")

    chunks: list[AudioOutput] = []
    async for out in provider.stream_sentence(
        TextChunk(text="Hola Hipotenusa.", voice_id="jane", sequence=0)
    ):
        chunks.append(out)

    assert chunks, "expected at least one audio chunk"
    assert any(c.samples for c in chunks), "expected non-empty PCM"
    assert chunks[-1].final
