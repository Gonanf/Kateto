import asyncio
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, InterruptData, TextChunk
from kateto.core.manager import PluginManager
from kateto.plugins.audio_output.edgetts import EdgeTTSAudioOutput
from kateto.plugins.audio_output.player import AudioOutputPlayer, SoundDeviceOutputStream


class DummyEdgeTTSProvider:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aclose(self):
        pass

    async def stream_sentence(self, sentence: TextChunk, *, voice: str):
        self.stream_calls += 1
        # Yield 2 chunks of PCM
        pcm_block = struct.pack("<100h", *[1000] * 100)
        yield AudioOutput(samples=pcm_block, sample_rate=24000, channels=1, voice_id=voice, sequence=0)
        await asyncio.sleep(0.02)
        yield AudioOutput(samples=b"", sample_rate=24000, channels=1, voice_id=voice, sequence=1, final=True)


@pytest.mark.asyncio
async def test_edgetts_preserves_voice_id_and_aborts_on_interrupt():
    manager = PluginManager()
    provider = DummyEdgeTTSProvider()
    settings = PluginSettings(enabled=True)
    plugin = EdgeTTSAudioOutput(
        settings,
        provider=provider,
        default_voice="es-AR-ElenaNeural",
    )
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)

    emitted_audio = []

    def _observer(env):
        if env.name == "audio_output":
            emitted_audio.append(env.data)

    manager.add_event_observer(_observer)

    # When: normal text chunk arrives for voice 'doktor'
    chunk = TextChunk(text="Hola mundo del debate", voice_id="doktor", sequence=0, final=True)
    await plugin.on_text_chunk(chunk)

    # Then: emitted AudioOutput preserves 'doktor' as voice_id (not the edge neural voice string)
    assert len(emitted_audio) >= 1
    assert emitted_audio[0].voice_id == "doktor"

    # Now test interruption aborts pending queues and resets playing
    await plugin.on_interrupt(InterruptData(reason="objection"))
    assert plugin._interrupted is True
    assert plugin.queue.empty()

    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_resumes_speech_on_next_turn_after_interrupt():
    manager = PluginManager()
    provider = DummyEdgeTTSProvider()
    settings = PluginSettings(enabled=True)
    plugin = EdgeTTSAudioOutput(
        settings,
        provider=provider,
        default_voice="es-AR-ElenaNeural",
    )
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)

    emitted_audio = []

    def _observer(env):
        if env.name == "audio_output":
            emitted_audio.append(env.data)

    manager.add_event_observer(_observer)

    # 1. First speaker starts talking
    await plugin.on_text_chunk(TextChunk(text="Argumento inicial", voice_id="jane", sequence=0, final=False))
    assert len(emitted_audio) >= 1

    # 2. Objection / interruption occurs
    await plugin.on_interrupt(InterruptData(reason="objection"))
    assert plugin._interrupted is True

    # 3. Trailing chunk from interrupted speech is dropped
    count_before = len(emitted_audio)
    await plugin.on_text_chunk(TextChunk(text="frase interrumpida", voice_id="jane", sequence=1, final=False))
    assert len(emitted_audio) == count_before

    # 4. Next speaker (or objection with sequence=0) speaks: TTS MUST resume!
    await plugin.on_text_chunk(TextChunk(text="¡Objeción! No estoy de acuerdo", voice_id="doktor", sequence=0, final=True))
    assert len(emitted_audio) > count_before
    assert plugin._interrupted is False
    assert emitted_audio[-1].voice_id == "doktor"

    await manager.close()


@pytest.mark.asyncio
async def test_audio_player_closes_stream_gracefully_on_interrupt():
    manager = PluginManager()
    settings = PluginSettings(enabled=True)
    player = AudioOutputPlayer(settings)
    manager.register_plugin(player)
    await manager.enable_plugin(player)

    mock_raw_stream = MagicMock()
    mock_raw_stream.abort = MagicMock()
    mock_raw_stream.stop = MagicMock()
    mock_raw_stream.close = MagicMock()
    mock_factory = MagicMock()
    mock_new_raw_stream = MagicMock()
    mock_new_raw_stream.active = False
    mock_new_raw_stream.start = MagicMock()
    mock_new_raw_stream.write = MagicMock(return_value=100)
    mock_factory.create.return_value = SoundDeviceOutputStream(mock_new_raw_stream, device=None)
    player._factory = mock_factory

    player._stream = SoundDeviceOutputStream(mock_raw_stream, device=None)
    player._stream_format = (24_000, 1)

    # When: interrupt arrives
    await player.on_interrupt(InterruptData(reason="objection"))

    # Then: PortAudio stream is stopped and closed (never abort() — abort triggers
    # double-free on xrun-corrupted streams in ALSA mmap path)
    mock_raw_stream.stop.assert_called_once()
    mock_raw_stream.close.assert_called_once()
    mock_raw_stream.abort.assert_not_called()
    assert player._stream is None

    # And when next audio output arrives for objection (conquest)
    await player.on_audio_output(AudioOutput(samples=b"\x00" * 4000, sample_rate=24000, channels=1, format="pcm_s16le", voice_id="conquest", sequence=0, final=False))
    assert mock_factory.create.called
    assert mock_new_raw_stream.start.called
    assert mock_new_raw_stream.write.called
    assert player._current_speaker == "conquest"

    await manager.close()
