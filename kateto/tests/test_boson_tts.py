from __future__ import annotations

import io
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kateto.core.config import (
    PluginConfigRegistry,
    PluginSettings,
    VoiceSettings,
    load_config,
    register_plugin_param,
    register_voice_param,
)
from kateto.core.event import AudioOutput, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.audio_output.boson_tts_plugin import BosonAudioOutput
from kateto.providers.boson_tts import BosonTTSProvider
from kateto.voices.prompt_blocks import get_agent_prompt_block


def test_get_agent_prompt_block_boson_tags():
    block = get_agent_prompt_block("boson")
    assert block is not None
    assert "Boson Higgs-TTS 3" in block
    # Verify that CFX/SFX, emotions, styles, and prosody are all explained:
    assert "<|emotion:" in block
    assert "<|style:" in block
    assert "<|prosody:" in block
    assert "<|sfx:" in block
    assert "<|prosody:pause|>" in block
    assert "<|sfx:laughter|>Haha" in block


@pytest.mark.asyncio
async def test_boson_tts_provider_speech_request():
    provider = BosonTTSProvider(api_key="sk-test-key", model="higgs-tts-3")

    mock_resp = MagicMock()
    mock_resp.content = b"fake-audio-wav-bytes"
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        audio_bytes = await provider.generate_speech("Hello world from Boson", voice="chloe")

        assert audio_bytes == b"fake-audio-wav-bytes"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "higgs-tts-3"
        assert call_kwargs["json"]["input"] == "Hello world from Boson"
        assert call_kwargs["json"]["voice"] == "chloe"
        assert call_kwargs["json"]["response_format"] == "wav"
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-test-key"


def test_plugins_can_add_dynamic_parameters_without_hardcoding_class(tmp_path: Path):
    # Given: a plugin registers a custom parameter on voice config and plugin config
    register_voice_param("custom_vibe", "chill")
    register_plugin_param("my_plugin", "cool_factor", 42)

    # And a config file uses these arbitrary/extra parameters
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("""\
[kateto]
debug = false

[cli]
allowlist = ["ls"]

[plugin.my_plugin]
cool_factor = 99
custom_runtime_flag = true

[voice.test_bot]
custom_vibe = "energetic"
another_arbitrary_voice_field = "awesome"
""", encoding="utf-8")

    # When: loading the config
    loaded = load_config(config_dir=config_dir)

    # Then: extra parameters are preserved and accessible without hardcoded class fields
    plugin_settings = loaded.settings.plugin["my_plugin"]
    assert plugin_settings.get("cool_factor") == 99
    assert plugin_settings.custom_runtime_flag is True

    voice_settings = loaded.settings.voice["test_bot"]
    assert voice_settings.get("custom_vibe") == "energetic"
    assert voice_settings.another_arbitrary_voice_field == "awesome"


def test_each_voice_folder_has_its_own_config(tmp_path: Path):
    # Given: a voice directory containing its own config.toml
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("""\
[kateto]
debug = false

[cli]
allowlist = ["ls"]
""", encoding="utf-8")

    # A voice folder with its own config.toml specifying its voice plugin instance parameters
    custom_voice_dir = config_dir / "voices" / "echo"
    custom_voice_dir.mkdir(parents=True)
    (custom_voice_dir / "config.toml").write_text("""\
enabled = true
dept = "fun"
tts_provider = "boson"
boson_voice = "jake"
custom_voice_rate = 1.2
""", encoding="utf-8")

    # When: loading config
    loaded = load_config(config_dir=config_dir)

    # Then: the voice is discovered and loaded from its folder config
    assert "echo" in loaded.settings.voice
    echo_settings = loaded.settings.voice["echo"]
    assert echo_settings.enabled is True
    assert echo_settings.tts_provider == "boson"
    assert echo_settings.get("boson_voice") == "jake"
    assert echo_settings.get("custom_voice_rate") == 1.2


@pytest.mark.asyncio
async def test_boson_audio_output_plugin_synthesizes_and_emits():
    # Given: a mock WAV payload
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 1024)
    fake_wav = buf.getvalue()

    provider = MagicMock()
    provider.generate_speech = AsyncMock(return_value=fake_wav)

    settings = PluginSettings()
    voice_map = {"jane": {"boson_voice": "chloe"}}
    plugin = BosonAudioOutput(settings, provider=provider, voice_map=voice_map)

    manager = PluginManager()
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)

    emitted_audio = []

    def observer(envelope):
        if envelope.name == "audio_output":
            emitted_audio.append(envelope.data)

    manager.add_event_observer(observer)

    # When: a text chunk arrives for Jane
    chunk = TextChunk(text="¡Hola tribunal! <|emotion:enthusiasm|>Estamos listos.", voice_id="jane", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: Boson provider was called with Jane's boson_voice
    provider.generate_speech.assert_called()
    assert provider.generate_speech.call_args.kwargs["voice"] == "chloe"

    # And audio_output events were emitted to the manager
    assert len(emitted_audio) > 0
    assert any(a.final for a in emitted_audio)
    await manager.close()


def test_get_agent_prompt_block_edgetts():
    block = get_agent_prompt_block("edge_tts")
    assert block is not None
    assert "Edge TTS" in block
    assert get_agent_prompt_block("edgetts") == block


def test_voice_folder_config_with_edge_tts(tmp_path: Path):
    # Given: a voice directory containing edge_tts_voice configuration
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("""\
[kateto]
debug = false

[cli]
allowlist = ["ls"]
""", encoding="utf-8")

    custom_voice_dir = config_dir / "voices" / "reporter"
    custom_voice_dir.mkdir(parents=True)
    (custom_voice_dir / "config.toml").write_text("""\
enabled = true
dept = "fun"
tts_provider = "edge_tts"
edge_tts_voice = "es-AR-ElenaNeural"
boson_voice = "chloe"
""", encoding="utf-8")

    # When: loading config
    loaded = load_config(config_dir=config_dir)

    # Then: edge_tts_voice is correctly loaded from the voice folder
    assert "reporter" in loaded.settings.voice
    reporter = loaded.settings.voice["reporter"]
    assert reporter.tts_provider == "edge_tts"
    assert reporter.get("edge_tts_voice") == "es-AR-ElenaNeural"
    assert reporter.get("boson_voice") == "chloe"
