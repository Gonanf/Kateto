from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kateto.core.config import VoiceSettings
from kateto.providers.boson_tts import BosonTTSProvider
from kateto.voices.prompt_blocks import get_agent_prompt_block


def test_get_agent_prompt_block_boson():
    block = get_agent_prompt_block("boson")
    assert block is not None
    assert "Boson TTS" in block


@pytest.mark.asyncio
async def test_boson_tts_provider_speech_request():
    provider = BosonTTSProvider(api_key="sk-test-key", model="higgs-tts-3")

    mock_resp = MagicMock()
    mock_resp.content = b"fake-audio-mp3-bytes"
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        audio_bytes = await provider.generate_speech("Hello world from Boson")

        assert audio_bytes == b"fake-audio-mp3-bytes"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["model"] == "higgs-tts-3"
        assert call_kwargs["json"]["input"] == "Hello world from Boson"
        assert "Authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-test-key"
