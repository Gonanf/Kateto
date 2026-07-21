from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData, TranscriptionData
from kateto.voices.base import GenerationRequest, VoiceAgent, VoiceProfile, VoiceRole


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


def _reference(config_dir: Path) -> None:
    path = config_dir / "voices" / "jane" / "reference.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFFfixtureWAVE")


@pytest.mark.asyncio
async def test_voice_provider_request_includes_bounded_event_history_once(tmp_path: Path) -> None:
    # Given: a voice that has received a transcription before its generation trigger.
    _reference(tmp_path)
    provider = RecordingProvider()
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: the same event-derived request is generated after context accumulation.
        await manager.emit("transcription", TranscriptionData(text="remember this context"), source="fixture")
        await manager.wait_for_idle()
        await manager.emit("generate", GenerateData(prompt="remember this context"), source="fixture")
        await manager.wait_for_idle()

        # Then: the provider sees retained context exactly once and the history is bounded.
        contents = [message.content for message in provider.requests[0].messages]
        assert contents.count("remember this context") == 1
        assert len(voice.message_history) <= 32
    finally:
        await manager.close()
