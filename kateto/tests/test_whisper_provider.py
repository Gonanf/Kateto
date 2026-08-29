from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kateto.core.config import PluginSettings
from kateto.core.event import AudioData
from kateto.core.exceptions import ProviderError
from kateto.plugins.audio_processor.whisper import WhisperAudioProcessor
from kateto.providers.whisper import (
    PyWhisperCppProvider,
    WhisperProvider,
    WhisperServerProcessProvider,
)


@pytest.mark.asyncio
async def test_pywhispercpp_provider_transcribes_using_model():
    # Given: a mock pywhispercpp Model
    mock_model_cls = MagicMock()
    mock_model_instance = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Hello world from pywhispercpp"
    mock_model_instance.transcribe.return_value = [mock_segment]
    mock_model_cls.return_value = mock_model_instance

    with patch.dict(sys.modules, {"pywhispercpp": MagicMock(), "pywhispercpp.model": MagicMock(Model=mock_model_cls)}):
        settings = PluginSettings(model="base.en")
        provider = PyWhisperCppProvider(settings)

        # When: transcribing audio
        audio = AudioData(
            samples=b"\x00\x00" * 1600,
            sample_rate=16000,
            channels=1,
            format="pcm_s16le",
        )
        result = await provider.transcribe(audio)

        # Then: the transcription is parsed from segments
        assert result.text == "Hello world from pywhispercpp"


@pytest.mark.asyncio
async def test_pywhispercpp_provider_raises_informative_error_when_missing():
    # Given: pywhispercpp not installed
    with patch.dict(sys.modules, {"pywhispercpp": None, "pywhispercpp.model": None}):
        provider = PyWhisperCppProvider(PluginSettings())
        audio = AudioData(samples=b"\x00\x00" * 100, format="pcm_s16le")

        # When / Then:
        with pytest.raises(ProviderError, match="pywhispercpp is not installed"):
            await provider.transcribe(audio)


@pytest.mark.asyncio
async def test_whisper_audio_processor_selects_pywhispercpp_backend():
    # Given: settings with backend="pywhispercpp"
    settings = PluginSettings(backend="pywhispercpp")
    processor = WhisperAudioProcessor(settings)

    # When: enabling with mocked provider
    with patch("kateto.providers.PyWhisperCppProvider") as mock_provider_cls:
        mock_instance = AsyncMock()
        mock_provider_cls.return_value = mock_instance
        await processor.enable()

        assert processor._provider == mock_instance
        mock_instance.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_whisper_audio_processor_selects_server_backend():
    # Given: settings with backend="server"
    settings = PluginSettings(backend="server")
    processor = WhisperAudioProcessor(settings)

    # When: enabling with mocked server process provider
    with patch("kateto.providers.WhisperServerProcessProvider") as mock_server_cls:
        mock_instance = AsyncMock()
        mock_server_cls.return_value = mock_instance
        await processor.enable()

        assert processor._provider == mock_instance
        mock_instance.__aenter__.assert_awaited_once()
