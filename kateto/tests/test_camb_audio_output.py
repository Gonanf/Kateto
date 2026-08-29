from __future__ import annotations

import io
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kateto.core.config import PluginSettings
from kateto.core.event import AudioOutput, TextChunk
from kateto.plugins.audio_output.camb import CambAudioOutput
from kateto.plugins.audio_output.player import AudioOutputPlayer
from kateto.providers._models import CambRequest
from kateto.providers.camb import CambProvider, _wav_to_pcm
from kateto.voices.base import AudioPipeline


def _make_dummy_wav(num_samples: int = 480, sample_rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * num_samples)
    return buffer.getvalue()


def test_camb_request_includes_wav_output_configuration():
    req = CambRequest(text="Hello", voice_id=147320)
    dump = req.model_dump(mode="json", exclude_none=True)
    assert dump.get("output_configuration") == {"format": "wav"}


def test_wav_to_pcm_parses_riff_wav():
    wav_bytes = _make_dummy_wav(240, 24000)
    pcm, rate = _wav_to_pcm(wav_bytes)
    assert rate == 24000
    assert len(pcm) == 480


@pytest.mark.asyncio
async def test_camb_provider_sets_voice_id_from_sentence():
    wav_bytes = _make_dummy_wav(240, 24000)
    settings = PluginSettings(api_key="test-key")
    provider = CambProvider(settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    async def _mock_chunks():
        yield wav_bytes
    mock_resp.aiter_bytes = _mock_chunks
    mock_resp.raise_for_status = MagicMock()

    mock_stream = MagicMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.stream.return_value = mock_stream
    mock_client.is_closed = False
    provider._client = mock_client
    provider._active = True

    sentence = TextChunk(text="Greetings", voice_id="conquest", sequence=0)
    outputs = [o async for o in provider.stream_sentence(sentence, voice_id=147320, language="en-us")]

    assert len(outputs) == 2
    assert outputs[0].voice_id == "conquest"
    assert outputs[0].samples == b"\x00\x00" * 240
    assert outputs[1].final is True
    assert outputs[1].voice_id == "conquest"


@pytest.mark.asyncio
async def test_player_forwards_samples_to_active_pipeline():
    # Given an active pipeline for "conquest"
    pipeline = AudioPipeline()
    with patch("kateto.plugins.audio_output.player.get_pipeline", return_value=pipeline):
        player = AudioOutputPlayer(PluginSettings())
        player._mixer_task = MagicMock()  # Mock mixer task so it doesn't run sounddevice

        # When: on_audio_output receives samples
        event = AudioOutput(
            samples=b"\x01\x00" * 10,
            sample_rate=24000,
            channels=1,
            format="pcm_s16le",
            voice_id="conquest",
            sequence=0,
            final=False,
        )
        await player.on_audio_output(event)

        # Then: samples are placed in pipeline.pcm_queue
        queued = await pipeline.pcm_queue.get()
        assert queued == b"\x01\x00" * 10
