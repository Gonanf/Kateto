from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk, WordTiming
from kateto.core.manager import PluginManager
from kateto.plugins.audio_output.edgetts import EdgeTTSAudioOutput
from kateto.plugins.audio_output.player import AudioOutputPlayer, SoundDeviceOutputStream
from kateto.plugins.visual_overlay.visual_overlay_plugin import VisualOverlayPlugin


def _words() -> list[WordTiming]:
    return [
        WordTiming(text="Hola", start_ms=0.0, end_ms=200.0),
        WordTiming(text="mundo", start_ms=200.0, end_ms=450.0),
    ]


def test_word_timing_model_rejects_empty_text_and_negative_times():
    with pytest.raises(ValidationError):
        WordTiming(text="", start_ms=0.0, end_ms=100.0)
    with pytest.raises(ValidationError):
        WordTiming(text="hola", start_ms=-1.0, end_ms=100.0)


def test_audio_output_accepts_optional_words():
    out = AudioOutput(
        samples=b"\x00\x00",
        sample_rate=24000,
        channels=1,
        format="pcm_s16le",
        voice_id="jane",
        text="Hola mundo",
        words=_words(),
    )
    assert [w.text for w in out.words or []] == ["Hola", "mundo"]
    assert AudioOutput(samples=b"\x00\x00", sample_rate=24000, channels=1).words is None


class WordDummyProvider:
    """EdgeTTS-shaped provider yielding text/words like the real one."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aclose(self):
        pass

    async def stream_sentence(self, sentence: TextChunk, *, voice: str):
        pcm_block = struct.pack("<100h", *[1000] * 100)
        yield AudioOutput(
            samples=pcm_block,
            sample_rate=24000,
            channels=1,
            voice_id=voice,
            sequence=0,
            text=sentence.text,
            words=[_words()[0]],
        )
        await asyncio.sleep(0.01)
        yield AudioOutput(
            samples=b"",
            sample_rate=24000,
            channels=1,
            voice_id=voice,
            sequence=1,
            final=True,
            text=sentence.text,
            words=_words(),
        )


@pytest.mark.asyncio
async def test_edgetts_plugin_forwards_sentence_text_and_word_timings():
    # Given: TTS for a sentence with word timings
    manager = PluginManager()
    plugin = EdgeTTSAudioOutput(
        PluginSettings(enabled=True),
        provider=WordDummyProvider(),
        default_voice="es-AR-ElenaNeural",
    )
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)
    emitted: list[AudioOutput] = []
    manager.add_event_observer(lambda env: emitted.append(env.data) if env.name == "audio_output" else None)

    # When: a sentence streams through
    await plugin.on_text_chunk(TextChunk(text="Hola mundo", voice_id="jane", sequence=0, final=True))

    # Then: chunks carry the sentence text for TTS-paced captions...
    assert emitted
    assert all(chunk.text == "Hola mundo" for chunk in emitted)
    # ...and the final event carries the complete word timings
    finals = [chunk for chunk in emitted if chunk.final]
    assert len(finals) == 1
    assert [w.text for w in finals[0].words or []] == ["Hola", "mundo"]

    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_plugin_drops_contentless_chunks():
    # Given: TTS wired to the bus
    manager = PluginManager()
    plugin = EdgeTTSAudioOutput(
        PluginSettings(enabled=True),
        provider=WordDummyProvider(),
        default_voice="es-AR-ElenaNeural",
    )
    manager.register_plugin(plugin)
    await manager.enable_plugin(plugin)
    emitted: list[AudioOutput] = []
    manager.add_event_observer(lambda env: emitted.append(env.data) if env.name == "audio_output" else None)

    # When: the LLM's contentless turn-final chunk arrives
    await plugin.on_text_chunk(TextChunk(text="   ", voice_id="jane", sequence=5, final=True))

    # Then: no bogus final sentinel is injected into the player lane
    assert emitted == []

    await manager.close()


@pytest.mark.asyncio
async def test_overlay_broadcast_carries_words_and_playback_clock():
    # Given: an overlay with a connected websocket
    vo = VisualOverlayPlugin()
    ws = MagicMock()
    ws.send_json = AsyncMock()
    await vo.register_websocket(ws)

    # When: an audio event with word timings arrives...
    await vo.on_audio_output(
        AudioOutput(
            samples=b"\x00\x00" * 100,
            sample_rate=24000,
            channels=1,
            format="pcm_s16le",
            voice_id="jane",
            text="Hola mundo",
            words=_words(),
        )
    )
    payload = ws.send_json.call_args[0][0]
    assert payload["text"] == "Hola mundo"
    assert [w["text"] for w in payload["words"]] == ["Hola", "mundo"]
    assert payload["data"]["words"][1]["start_ms"] == 200.0

    # ...and a post-write viseme reports sentence-relative playback time
    await vo.update_viseme("jane", 0.4, audio_ms=210.0)
    viseme = ws.send_json.call_args[0][0]
    assert viseme["type"] == "viseme"
    assert viseme["audio_ms"] == 210.0
    assert viseme["data"]["audio_ms"] == 210.0


@pytest.mark.asyncio
async def test_player_plays_sentence_queued_behind_draining_final():
    # Given: a player with mocked device; sentence 2 fully queued while
    # sentence 1 still drains (synthesis outruns realtime playback)
    manager = PluginManager()
    player = AudioOutputPlayer(PluginSettings(enabled=True))
    manager.register_plugin(player)
    await manager.enable_plugin(player)

    mock_stream = MagicMock()
    mock_stream.active = False
    factory = MagicMock()
    factory.create.return_value = SoundDeviceOutputStream(mock_stream, device=None)
    player._factory = factory

    s1 = b"\x01\x00" * 2400
    s2 = b"\x02\x00" * 2400

    def _chunk(samples: bytes, seq: int, *, final: bool = False) -> AudioOutput:
        return AudioOutput(
            samples=samples, sample_rate=24000, channels=1,
            format="pcm_s16le", voice_id="jane", sequence=seq, final=final,
        )

    # When: s1 streams, s1 final closes its lane, then s2 arrives fully
    await player.on_audio_output(_chunk(s1, 0))
    await player.on_audio_output(_chunk(b"", 1, final=True))
    await player.on_audio_output(_chunk(s2, 0))
    await player.on_audio_output(_chunk(b"", 1, final=True))
    deadline = asyncio.get_running_loop().time() + 5.0
    while mock_stream.write.call_count < 2:
        assert asyncio.get_running_loop().time() < deadline, "mixer never played both sentences"
        await asyncio.sleep(0.01)
    await manager.wait_for_idle()

    # Then: both sentences reach the device in order (s2 is not orphaned
    # when s1's final sentinel pops s1's lane)
    written = [call.args[0] for call in mock_stream.write.call_args_list]
    assert written == [s1, s2]

    await manager.close()


@pytest.mark.asyncio
async def test_player_rescues_sentence_stranded_by_shared_queue_pop():
    # Given: a pipeline-path voice (shared queue across sentences) where the
    # next sentence is fully queued behind the previous sentence's final
    manager = PluginManager()
    player = AudioOutputPlayer(PluginSettings(enabled=True))
    manager.register_plugin(player)
    await manager.enable_plugin(player)

    mock_stream = MagicMock()
    mock_stream.active = False
    factory = MagicMock()
    factory.create.return_value = SoundDeviceOutputStream(mock_stream, device=None)
    player._factory = factory

    from types import SimpleNamespace

    shared = SimpleNamespace(pcm_queue=asyncio.Queue())
    s1 = b"\x01\x00" * 2400
    s2 = b"\x02\x00" * 2400

    def _chunk(samples: bytes, seq: int, *, final: bool = False) -> AudioOutput:
        return AudioOutput(
            samples=samples, sample_rate=24000, channels=1,
            format="pcm_s16le", voice_id="doktor", sequence=seq, final=final,
        )

    with patch("kateto.plugins.audio_output.player.get_pipeline", return_value=shared):
        # When: s1, s1-final, s2, s2-final all land before the mixer drains
        await player.on_audio_output(_chunk(s1, 0))
        await player.on_audio_output(_chunk(b"", 1, final=True))
        await player.on_audio_output(_chunk(s2, 0))
        await player.on_audio_output(_chunk(b"", 1, final=True))
        deadline = asyncio.get_running_loop().time() + 5.0
        while mock_stream.write.call_count < 2:
            assert asyncio.get_running_loop().time() < deadline, "stranded sentence never rescued"
            await asyncio.sleep(0.01)

    # Then: the sentence stranded by the pop still reaches the device in order
    written = [call.args[0] for call in mock_stream.write.call_args_list]
    assert written == [s1, s2]

    await manager.close()


@pytest.mark.asyncio
async def test_player_reports_sentence_relative_playback_ms():    # Given: a player with mocked device and a spying overlay
    manager = PluginManager()
    player = AudioOutputPlayer(PluginSettings(enabled=True))
    vo = VisualOverlayPlugin()
    manager.register_plugin(player)
    manager.register_plugin(vo)
    await manager.enable_plugin(player)
    await manager.enable_plugin(vo)

    mock_stream = MagicMock()
    mock_stream.active = False
    mock_stream.start = MagicMock()
    mock_stream.write = MagicMock(return_value=100)
    factory = MagicMock()
    factory.create.return_value = SoundDeviceOutputStream(mock_stream, device=None)
    player._factory = factory

    seen_clocks: list[float | None] = []
    with patch.object(vo, "update_viseme") as visemes:
        visemes.side_effect = lambda *args, **kwargs: seen_clocks.append(kwargs.get("audio_ms"))
        # When: two 4800-byte chunks play at 24kHz mono s16le (100ms each)
        await player.on_audio_output(
            AudioOutput(samples=b"\x01\x00" * 2400, sample_rate=24000, channels=1, format="pcm_s16le", voice_id="jane", sequence=0, final=False)
        )
        await player.on_audio_output(
            AudioOutput(samples=b"\x01\x00" * 2400, sample_rate=24000, channels=1, format="pcm_s16le", voice_id="jane", sequence=1, final=False)
        )
        await player.on_audio_output(
            AudioOutput(samples=b"", sample_rate=24000, channels=1, format="pcm_s16le", voice_id="jane", sequence=2, final=True)
        )
        deadline = asyncio.get_running_loop().time() + 5.0
        while len(seen_clocks) < 2:
            assert asyncio.get_running_loop().time() < deadline, "mixer never played both chunks"
            await asyncio.sleep(0.01)

    # Then: visemes carry cumulative sentence-relative playback time
    clocks = sorted(seen_clocks)
    assert clocks[0] == pytest.approx(100.0)
    assert clocks[1] == pytest.approx(200.0)

    await manager.close()


@pytest.mark.asyncio
async def test_player_skips_wedged_head_lane_without_10s_stall():
    # Given: voice A wedged (chunk played, final never comes) while voice B
    # has a complete sentence queued behind it
    manager = PluginManager()
    player = AudioOutputPlayer(PluginSettings(enabled=True))
    manager.register_plugin(player)
    await manager.enable_plugin(player)

    mock_stream = MagicMock()
    mock_stream.active = False
    factory = MagicMock()
    factory.create.return_value = SoundDeviceOutputStream(mock_stream, device=None)
    player._factory = factory

    def _chunk(voice: str, samples: bytes, seq: int, *, final: bool = False) -> AudioOutput:
        return AudioOutput(
            samples=samples, sample_rate=24000, channels=1,
            format="pcm_s16le", voice_id=voice, sequence=seq, final=final,
        )

    # When: A's lane drains with no final in sight, B arrives complete
    await player.on_audio_output(_chunk("jane", b"\x01\x00" * 2400, 0))
    await player.on_audio_output(_chunk("doktor", b"\x02\x00" * 2400, 0))
    await player.on_audio_output(_chunk("doktor", b"", 1, final=True))
    deadline = asyncio.get_running_loop().time() + 3.0
    while mock_stream.write.call_count < 2:
        assert asyncio.get_running_loop().time() < deadline, "wedged head lane muted the next voice"
        await asyncio.sleep(0.01)

    # Then: B played without waiting out the 10s stall-drop
    written = [call.args[0] for call in mock_stream.write.call_args_list]
    assert written == [b"\x01\x00" * 2400, b"\x02\x00" * 2400]

    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_provider_yields_final_on_read_error():
    # Given: ffmpeg stdout failing mid-sentence
    import sys

    from kateto.core.event import TextChunk
    from kateto.providers.edgetts import EdgeTTSProvider

    async def _stream():
        yield {"type": "WordBoundary", "text": "hola", "offset": 0, "duration": 2000000}
        await asyncio.sleep(0.05)
        yield {"type": "audio", "data": b"\x01\x02"}

    communicator = MagicMock()
    communicator.stream.side_effect = lambda: _stream()
    edge_tts = MagicMock()
    edge_tts.Communicate.return_value = communicator

    stdin = MagicMock()
    stdin.drain = AsyncMock()
    stdout = MagicMock()
    reads = iter([b"\x00\x00" * 50, RuntimeError("pipe gone")])

    async def _read(_n: int) -> bytes:
        await asyncio.sleep(0.05)
        item = next(reads)
        if isinstance(item, BaseException):
            raise item
        return item

    stdout.read = _read
    proc = MagicMock()
    proc.stdin = stdin
    proc.stdout = stdout
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)

    provider = EdgeTTSProvider(PluginSettings(), voice="es-AR-ElenaNeural")
    with (
        patch.dict(sys.modules, {"edge_tts": edge_tts}),
        patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)),
    ):
        outputs = [out async for out in provider.stream_sentence(TextChunk(text="hola mundo", voice_id="jane", sequence=0), voice="es-AR-ElenaNeural")]

    # Then: the pcm chunk plus a closing final (lane closes instead of wedging)
    assert [o.final for o in outputs] == [False, True]
    assert outputs[-1].text == "hola mundo"
    assert [w.text for w in outputs[-1].words or []] == ["hola"]
