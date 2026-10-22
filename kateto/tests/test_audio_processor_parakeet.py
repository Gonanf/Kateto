from __future__ import annotations

from typing import Any
import httpx
import pytest

from kateto.core import PluginManager
from kateto.core.config import PluginSettings
from kateto.core.event import AudioData, TranscriptionData
from kateto.core.plugin import Plugin
from kateto.plugins.audio_processor.parakeet import (
    DEFAULT_PARAKEET_ENDPOINT,
    DEFAULT_PARAKEET_MODEL,
    ParakeetAudioProcessor,
)


class FakeClient:
    """AsyncClient fixture that captures POST requests and returns canned responses."""

    def __init__(
        self,
        *,
        response: httpx.Response | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = (
            response
            if response is not None
            else httpx.Response(200, json={"text": "fixture transcription"})
        )
        self.error = error
        self.closed = False

    async def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        timeout: float,
    ) -> httpx.Response:
        self.calls.append({
            "method": "POST",
            "url": url,
            "data": data,
            "files": files,
            "timeout": timeout,
        })
        if self.error is not None:
            raise self.error
        resp = self.response
        if getattr(resp, "_request", None) is None:
            resp._request = httpx.Request("POST", url)
        return resp

    async def aclose(self) -> None:
        self.closed = True


class TranscriptionSink(Plugin):
    """Event subscriber sink that records transcription events."""

    def __init__(self) -> None:
        super().__init__("transcription_sink")
        self.received: list[TranscriptionData] = []

    async def on_transcription(self, data: TranscriptionData) -> None:
        self.received.append(data)


@pytest.mark.asyncio
async def test_post_request_structure_and_wav_payload() -> None:
    # Given: ParakeetAudioProcessor enabled with a fake client capturing HTTP POST.
    manager = PluginManager()
    settings = PluginSettings(endpoint="http://127.0.0.1:8098", language="es")
    processor = ParakeetAudioProcessor(settings)
    fake_client = FakeClient(response=httpx.Response(200, json={"text": "hola mundo"}))
    sink = TranscriptionSink()

    await manager.enable_plugin(processor)
    processor._client = fake_client
    await manager.enable_plugin(sink)

    try:
        # When: an audio chunk enters the event bus.
        audio = AudioData(
            samples=b"\x01\x00" * 1600,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
            duration_ms=100.0,
        )
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()

        # Then: exactly one POST request was sent to {endpoint}/v1/audio/transcriptions.
        assert len(fake_client.calls) == 1
        call = fake_client.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "http://127.0.0.1:8098/v1/audio/transcriptions"
        assert call["data"] == {
            "model": "parakeet",
            "response_format": "json",
            "temperature": "0.0",
            "language": "es",
        }

        # And: files["file"] contains an audio/wav payload starting with RIFF/WAVE header.
        file_tuple = call["files"]["file"]
        assert len(file_tuple) == 3
        filename, wav_bytes, mime_type = file_tuple
        assert filename == "audio.wav"
        assert mime_type == "audio/wav"
        assert wav_bytes.startswith(b"RIFF")
        assert b"WAVE" in wav_bytes[:12]

        # And: sink received the transcription.
        assert len(sink.received) == 1
        assert sink.received[0].text == "hola mundo"
        assert sink.received[0].duration_ms == 100.0
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("voice", ["doktor", "conquest", "jane", "whisperer", None])
async def test_voice_attribute_preserved_in_transcription(voice: str | None) -> None:
    # Given: Parakeet processor wired to receive an audio chunk carrying a specific voice.
    manager = PluginManager()
    processor = ParakeetAudioProcessor(PluginSettings())
    fake_client = FakeClient(response=httpx.Response(200, json={"text": "transcription result"}))
    sink = TranscriptionSink()

    await manager.enable_plugin(processor)
    processor._client = fake_client
    await manager.enable_plugin(sink)

    try:
        # When: an audio chunk carrying the voice attribute arrives.
        audio = AudioData(
            samples=b"\x01\x00" * 800,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
            voice=voice,
        )
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()

        # Then: the emitted transcription preserves the voice attribute.
        assert len(sink.received) == 1
        assert sink.received[0].voice == voice
        assert sink.received[0].text == "transcription result"
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_text", ["", "   ", "\t\n  \r"])
async def test_silence_empty_text_does_not_emit_transcription(empty_text: str) -> None:
    # Given: Parakeet API returning empty or whitespace text (silence / no speech).
    manager = PluginManager()
    processor = ParakeetAudioProcessor(PluginSettings())
    fake_client = FakeClient(response=httpx.Response(200, json={"text": empty_text}))
    sink = TranscriptionSink()

    await manager.enable_plugin(processor)
    processor._client = fake_client
    await manager.enable_plugin(sink)

    try:
        # When: an audio chunk is processed.
        audio = AudioData(
            samples=b"\x01\x00" * 800,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
        )
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()

        # Then: no transcription event is emitted.
        assert sink.received == []
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=httpx.Request("POST", "http://127.0.0.1:8098/v1/audio/transcriptions"),
            response=httpx.Response(500),
        ),
        httpx.ConnectError("Connection refused"),
        httpx.ReadTimeout("Read timed out"),
    ],
)
async def test_http_error_does_not_propagate_and_does_not_emit(error: Exception) -> None:
    # Given: Parakeet endpoint raising an HTTP or network error.
    manager = PluginManager()
    processor = ParakeetAudioProcessor(PluginSettings())
    fake_client = FakeClient(error=error)
    sink = TranscriptionSink()

    await manager.enable_plugin(processor)
    processor._client = fake_client
    await manager.enable_plugin(sink)

    try:
        # When: an audio chunk is processed while the endpoint fails.
        audio = AudioData(
            samples=b"\x01\x00" * 800,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
        )
        # Then: no exception propagates out of the event bus and no transcription is emitted.
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()
        assert sink.received == []
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_json_decode_error_does_not_propagate_and_does_not_emit() -> None:
    # Given: Parakeet endpoint returning invalid JSON content.
    manager = PluginManager()
    processor = ParakeetAudioProcessor(PluginSettings())
    fake_client = FakeClient(response=httpx.Response(200, content=b"502 Bad Gateway - Not JSON"))
    sink = TranscriptionSink()

    await manager.enable_plugin(processor)
    processor._client = fake_client
    await manager.enable_plugin(sink)

    try:
        # When: an audio chunk is processed.
        audio = AudioData(
            samples=b"\x01\x00" * 800,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
        )
        # Then: no exception propagates and no transcription is emitted.
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()
        assert sink.received == []
    finally:
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings", "expected_url"),
    [
        (PluginSettings(), f"{DEFAULT_PARAKEET_ENDPOINT}/v1/audio/transcriptions"),
        (
            PluginSettings(endpoint="http://parakeet.local:8098"),
            "http://parakeet.local:8098/v1/audio/transcriptions",
        ),
        (
            PluginSettings(endpoint="http://parakeet.local:8098/"),
            "http://parakeet.local:8098/v1/audio/transcriptions",
        ),
    ],
)
async def test_endpoint_resolution_from_settings(
    settings: PluginSettings,
    expected_url: str,
) -> None:
    # Given: Parakeet processor configured with either default or explicit endpoint.
    manager = PluginManager()
    processor = ParakeetAudioProcessor(settings)
    fake_client = FakeClient(response=httpx.Response(200, json={"text": "ping"}))

    await manager.enable_plugin(processor)
    processor._client = fake_client

    try:
        # When: an audio chunk is processed.
        audio = AudioData(
            samples=b"\x01\x00" * 800,
            sample_rate=16_000,
            channels=1,
            format="pcm_s16le",
            source="mask",
        )
        await manager.emit("audio_chunk", audio, source="audio_input_mask/mask")
        await manager.wait_for_idle()

        # Then: the request was directed to expected_url.
        assert len(fake_client.calls) == 1
        assert fake_client.calls[0]["url"] == expected_url
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_processor_lifecycle_enable_and_disable() -> None:
    # Given: a processor before being enabled.
    processor = ParakeetAudioProcessor(PluginSettings())
    assert processor._client is None

    # When: enabled, an httpx.AsyncClient is created.
    await processor.enable()
    client = processor._client
    assert isinstance(client, httpx.AsyncClient)
    assert not client.is_closed

    # And: disabled, the client is cleanly closed and reference reset to None.
    await processor.disable()
    assert processor._client is None
    assert client.is_closed


@pytest.mark.asyncio
async def test_chunk_ignored_when_client_is_none() -> None:
    # Given: a processor not enabled (no client).
    processor = ParakeetAudioProcessor(PluginSettings())
    audio = AudioData(
        samples=b"\x01\x00" * 800,
        sample_rate=16_000,
        channels=1,
        format="pcm_s16le",
        source="mask",
    )

    # When / Then: on_audio_chunk returns safely without raising.
    await processor.on_audio_chunk(audio)
