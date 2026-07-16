from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk
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
    await manager.close()
