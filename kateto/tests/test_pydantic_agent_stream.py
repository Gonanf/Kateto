from unittest.mock import AsyncMock, MagicMock

import pytest

from kateto.core.config import VoiceSettings
from kateto.voices.base import VoiceAgent, VoiceProfile, VoiceRole


@pytest.mark.asyncio
async def test_pydantic_agent_loop_streams_text(tmp_path):
    profile = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="Test system prompt",
        relevance_terms=frozenset({"test"}),
    )
    voice = VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=MagicMock(),
        settings=VoiceSettings(stream=True),
    )

    # Mock Pydantic AI agent
    mock_agent = MagicMock()

    class FakeStreamResult:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def stream_text(self, delta=True):
            yield "Hello "
            yield "world"

        def get_output(self):
            return "Hello world"

    mock_agent.run_stream.return_value = FakeStreamResult()
    voice.set_pydantic_agent(mock_agent)

    # Run loop
    await voice._pydantic_agent_loop("say hi", workflow=None, phase_id=None)
