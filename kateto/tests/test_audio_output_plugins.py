from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, AudioOutputStatus, AudioOutputStatusData, TextChunk
from kateto.plugins.audio_output.camb import CambAudioOutput
from kateto.plugins.audio_output.edgetts import EdgeTTSAudioOutput
from kateto.plugins.audio_output.player import AudioOutputPlayer
from kateto.plugins.audio_output.zonos import ZonosAudioOutput


class RecordingAudioOutput(Plugin):
    def __init__(self) -> None:
        super().__init__("audio_output_recorder")
        self.outputs: list[AudioOutput] = []

    async def on_audio_output(self, data: AudioOutput) -> None:
        self.outputs.append(data)


class StreamingPcmProvider:
    def __init__(self) -> None:
        self.entered: bool = False
        self.closed: bool = False
        self.requests: list[tuple[TextChunk, str]] = []

    async def __aenter__(self) -> StreamingPcmProvider:
        self.entered = True
        return self

    async def aclose(self) -> None:
        self.closed = True

    def stream_sentence(self, sentence: TextChunk, *, voice_id: str) -> AsyncIterator[AudioOutput]:
        self.requests.append((sentence, voice_id))
        return self._stream(sentence, voice_id)

    async def _stream(self, sentence: TextChunk, voice_id: str) -> AsyncIterator[AudioOutput]:
        yield AudioOutput(
            samples=b"\x01\x00\x02\x00",
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


@pytest.mark.asyncio
async def test_zonos_streams_pcm_audio_output_from_text_chunk_and_closes_provider() -> None:
    # Given: a managed Zonos output boundary with an injected PCM provider.
    manager = PluginManager()
    provider = StreamingPcmProvider()
    zonos = ZonosAudioOutput(PluginSettings(endpoint="http://zonos.test"), provider=provider)
    recorder = RecordingAudioOutput()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(zonos)

    # When: a voice emits a text chunk with its stable voice identifier.
    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="hello", sequence=4, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()

    # Then: the boundary emits the provider's PCM chunks as production audio_output events.
    assert provider.entered
    assert provider.requests == [(TextChunk(text="hello", sequence=4, final=True, voice_id="jane"), "jane")]
    assert recorder.outputs == [
        AudioOutput(
            samples=b"\x01\x00\x02\x00",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id="jane",
            sequence=4,
        ),
        AudioOutput(
            samples=b"",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id="jane",
            sequence=5,
            final=True,
        ),
    ]
    assert [event.source for event in manager.get_events() if event.name == "audio_output"] == ["audio_output_zonos"] * 2
    assert [event.data for event in manager.get_events() if event.name == "audio_output_status"] == [
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
    ]
    await manager.close()
    assert provider.closed


@pytest.mark.asyncio
async def test_player_consumes_pcm_and_stops_on_final_and_interrupt() -> None:
    # Given: a managed PCM player with a fake OS output stream factory.
    manager = PluginManager()
    factory = RecordingOutputFactory()
    player = AudioOutputPlayer(PluginSettings(device="Fixture Output"), player_factory=factory)
    await manager.enable_plugin(player)

    # When: it receives PCM, its final marker, then an interrupt during a second playback window.
    _ = await manager.emit(
        "audio_output",
        AudioOutput(samples=b"\x01\x00", sample_rate=24_000, channels=1, format="pcm_s16le"),
        source="audio_output_zonos",
    )
    await manager.wait_for_idle()
    _ = await manager.emit(
        "audio_output",
        AudioOutput(samples=b"", sample_rate=24_000, channels=1, format="pcm_s16le", final=True),
        source="audio_output_zonos",
    )
    await manager.wait_for_idle()
    _ = await manager.emit(
        "audio_output",
        AudioOutput(samples=b"\x03\x00", sample_rate=24_000, channels=1, format="pcm_s16le"),
        source="audio_output_zonos",
    )
    await manager.wait_for_idle()
    _ = await manager.interrupt(source="audio_input_mic/mic")
    await manager.wait_for_idle()

    # Then: PCM reaches the system boundary and both terminal conditions close playback.
    assert factory.requests == [("Fixture Output", 24_000, 1), ("Fixture Output", 24_000, 1)]
    assert [stream.writes for stream in factory.streams] == [[b"\x01\x00"], [b"\x03\x00"]]
    assert all(stream.started and stream.stopped and stream.closed for stream in factory.streams)
    assert [event.data for event in manager.get_events() if event.name == "audio_output_status"] == [
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
        AudioOutputStatusData(status=AudioOutputStatus.PLAYING),
        AudioOutputStatusData(status=AudioOutputStatus.IDLE),
    ]
    await manager.close()


class RecordingCambProvider:
    def __init__(self) -> None:
        self.entered: bool = False
        self.closed: bool = False
        self.requests: list[tuple[TextChunk, int, str]] = []

    async def __aenter__(self) -> RecordingCambProvider:
        self.entered = True
        return self

    async def aclose(self) -> None:
        self.closed = True

    async def stream_sentence(
        self, sentence: TextChunk, *, voice_id: int, language: str
    ) -> AsyncIterator[AudioOutput]:
        self.requests.append((sentence, voice_id, language))
        yield AudioOutput(
            samples=b"\x05\x00\x06\x00",
            sample_rate=48_000,
            channels=1,
            format="pcm_s16le",
            voice_id=str(voice_id),
            sequence=sentence.sequence,
        )
        yield AudioOutput(
            samples=b"",
            sample_rate=48_000,
            channels=1,
            format="pcm_s16le",
            voice_id=str(voice_id),
            sequence=sentence.sequence + 1,
            final=True,
        )


@pytest.mark.asyncio
async def test_camb_streams_pcm_with_voice_map_lookup() -> None:
    manager = PluginManager()
    provider = RecordingCambProvider()
    voice_map = {
        "jane": {"camb_voice_id": 999, "camb_language": "es-es"},
    }
    camb = CambAudioOutput(
        PluginSettings(endpoint="http://camb.test"),
        provider=provider,
        voice_map=voice_map,
        default_voice_id=147320,
        default_language="en-us",
    )
    recorder = RecordingAudioOutput()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(camb)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="hola", sequence=2, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()

    assert provider.entered
    assert provider.requests == [(TextChunk(text="hola", sequence=2, final=True, voice_id="jane"), 999, "es-es")]
    assert recorder.outputs == [
        AudioOutput(samples=b"\x05\x00\x06\x00", sample_rate=48_000, channels=1, format="pcm_s16le", voice_id="999", sequence=2),
        AudioOutput(samples=b"", sample_rate=48_000, channels=1, format="pcm_s16le", voice_id="999", sequence=3, final=True),
    ]
    assert [event.source for event in manager.get_events() if event.name == "audio_output"] == ["audio_output_camb"] * 2
    await manager.close()
    assert provider.closed


@pytest.mark.asyncio
async def test_camb_falls_back_to_default_voice_id_and_language() -> None:
    manager = PluginManager()
    provider = RecordingCambProvider()
    camb = CambAudioOutput(
        PluginSettings(endpoint="http://camb.test"),
        provider=provider,
        voice_map={},
        default_voice_id=147320,
        default_language="en-us",
    )
    recorder = RecordingAudioOutput()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(camb)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="hello", sequence=0, final=True, voice_id="unknown"),
        source="unknown",
    )
    await manager.wait_for_idle()

    assert provider.requests == [(TextChunk(text="hello", sequence=0, final=True, voice_id="unknown"), 147320, "en-us")]
    await manager.close()


@pytest.mark.asyncio
async def test_camb_ignores_text_chunk_without_voice_id() -> None:
    manager = PluginManager()
    provider = RecordingCambProvider()
    camb = CambAudioOutput(
        PluginSettings(endpoint="http://camb.test"),
        provider=provider,
    )
    await manager.enable_plugin(camb)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="skip me", sequence=0, final=True, voice_id=None),
        source="test",
    )
    await manager.wait_for_idle()

    assert provider.requests == []
    await manager.close()


@pytest.mark.asyncio
async def test_camb_plugin_lifecycle_provider_open_and_close() -> None:
    manager = PluginManager()
    provider = RecordingCambProvider()
    camb = CambAudioOutput(
        PluginSettings(endpoint="http://camb.test"),
        provider=provider,
    )
    await manager.enable_plugin(camb)
    assert provider.entered

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="test", sequence=0, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()

    await manager.close()
    assert provider.closed


class RecordingEdgeTTSProvider:
    def __init__(self) -> None:
        self.entered: bool = False
        self.closed: bool = False
        self.requests: list[tuple[TextChunk, str]] = []

    async def __aenter__(self) -> RecordingEdgeTTSProvider:
        self.entered = True
        return self

    async def aclose(self) -> None:
        self.closed = True

    async def stream_sentence(
        self, sentence: TextChunk, *, voice: str
    ) -> AsyncIterator[AudioOutput]:
        self.requests.append((sentence, voice))
        yield AudioOutput(
            samples=b"\x0a\x00\x0b\x00",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=sentence.sequence,
        )
        yield AudioOutput(
            samples=b"",
            sample_rate=24_000,
            channels=1,
            format="pcm_s16le",
            voice_id=voice,
            sequence=sentence.sequence + 1,
            final=True,
        )


@pytest.mark.asyncio
async def test_edgetts_streams_pcm_with_voice_map_lookup() -> None:
    manager = PluginManager()
    provider = RecordingEdgeTTSProvider()
    voice_map = {
        "jane": {"edge_tts_voice": "es-ES-AlvaroNeural"},
    }
    edge = EdgeTTSAudioOutput(
        PluginSettings(),
        provider=provider,
        voice_map=voice_map,
        default_voice="en-US-JennyNeural",
    )
    recorder = RecordingAudioOutput()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(edge)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="hola", sequence=2, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()

    assert provider.entered
    assert provider.requests == [(TextChunk(text="hola", sequence=2, final=True, voice_id="jane"), "es-ES-AlvaroNeural")]
    assert recorder.outputs == [
        AudioOutput(samples=b"\x0a\x00\x0b\x00", sample_rate=24_000, channels=1, format="pcm_s16le", voice_id="es-ES-AlvaroNeural", sequence=2),
        AudioOutput(samples=b"", sample_rate=24_000, channels=1, format="pcm_s16le", voice_id="es-ES-AlvaroNeural", sequence=3, final=True),
    ]
    assert [event.source for event in manager.get_events() if event.name == "audio_output"] == ["audio_output_edgetts"] * 2
    await manager.close()
    assert provider.closed


@pytest.mark.asyncio
async def test_edgetts_falls_back_to_default_voice() -> None:
    manager = PluginManager()
    provider = RecordingEdgeTTSProvider()
    edge = EdgeTTSAudioOutput(
        PluginSettings(),
        provider=provider,
        voice_map={},
        default_voice="en-GB-SoniaNeural",
    )
    recorder = RecordingAudioOutput()
    await manager.enable_plugin(recorder)
    await manager.enable_plugin(edge)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="hello", sequence=0, final=True, voice_id="unknown"),
        source="unknown",
    )
    await manager.wait_for_idle()

    assert provider.requests == [(TextChunk(text="hello", sequence=0, final=True, voice_id="unknown"), "en-GB-SoniaNeural")]
    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_ignores_text_chunk_without_voice_id() -> None:
    manager = PluginManager()
    provider = RecordingEdgeTTSProvider()
    edge = EdgeTTSAudioOutput(
        PluginSettings(),
        provider=provider,
    )
    await manager.enable_plugin(edge)

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="skip me", sequence=0, final=True, voice_id=None),
        source="test",
    )
    await manager.wait_for_idle()

    assert provider.requests == []
    await manager.close()


@pytest.mark.asyncio
async def test_edgetts_plugin_lifecycle_provider_open_and_close() -> None:
    manager = PluginManager()
    provider = RecordingEdgeTTSProvider()
    edge = EdgeTTSAudioOutput(
        PluginSettings(),
        provider=provider,
    )
    await manager.enable_plugin(edge)
    assert provider.entered

    _ = await manager.emit(
        "text_chunk",
        TextChunk(text="test", sequence=0, final=True, voice_id="jane"),
        source="jane",
    )
    await manager.wait_for_idle()

    await manager.close()
    assert provider.closed
