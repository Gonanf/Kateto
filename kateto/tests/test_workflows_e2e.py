"""End-to-end tests against the live Ollama server.

Requires llama.cpp/Ollama at http://127.0.0.1:11434/v1 with model "Kateto".

Run: uv run pytest kateto/tests/test_workflows_e2e.py -v
Skip with -m "not e2e".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData, TextChunk, VoiceIdleData
from kateto.providers import ChatMessage
from kateto.voices.base import (
    OpenAICompatibleProvider,
    VoiceAgent,
    VoiceProfile,
    VoiceRole,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

OLLAMA_ENDPOINT = "http://127.0.0.1:11434/v1"
OLLAMA_MODEL = "Kateto"


def _write_reference(config_dir: Path, voice: str) -> Path:
    ref = config_dir / "voices" / voice / "reference.wav"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"RIFFfixtureWAVE")
    return ref


async def test_live_provider_streams_completion() -> None:
    """Raw OpenAICompatibleProvider streams text from Ollama."""
    provider = OpenAICompatibleProvider(
        model=OLLAMA_MODEL,
        endpoint=OLLAMA_ENDPOINT,
        api_key="sk-no-key-required",
    )
    request = type(
        "GenRequest",
        (),
        {
            "voice_id": "jane",
            "reference_wav": Path("/dev/null"),
            "messages": (
                ChatMessage(role="system", content="You are Jane, a project coordinator."),
                ChatMessage(role="user", content="Summarize project management in one sentence."),
            ),
        },
    )()

    tokens: list[str] = []
    async for token in provider.stream(request):
        tokens.append(token)

    full = "".join(tokens)
    assert len(full) > 20, f"Expected substantial response, got {len(full)} chars: {full[:100]}"
    assert "project" in full.lower() or "management" in full.lower()


async def test_e2e_voice_generates_through_ollama() -> None:
    """VoiceAgent with live Ollama provider produces text_chunks on generate."""
    tmp_path = Path("/tmp/kateto-e2e-test")
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "voices" / "jane").mkdir(parents=True, exist_ok=True)
    _write_reference(tmp_path, "jane")

    manager = PluginManager()
    provider = OpenAICompatibleProvider(
        model=OLLAMA_MODEL,
        endpoint=OLLAMA_ENDPOINT,
        api_key="sk-no-key-required",
    )
    profile = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Jane, a calm project orchestrator. Keep responses brief.",
        relevance_terms=frozenset({"coordinate", "project"}),
    )
    voice = VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    await manager.enable_plugin(voice)

    try:
        await manager.emit(
            "generate",
            GenerateData(prompt="Briefly describe your role in the project."),
            source="fixture",
        )
        await manager.wait_for_idle(timeout=60)

        chunks = [
            event.data
            for event in manager.get_events()
            if event.name == "text_chunk" and isinstance(event.data, TextChunk)
        ]
        assert len(chunks) > 0, "Expected at least one text chunk from Ollama"
        full_text = "".join(c.text for c in chunks)
        assert len(full_text) > 5, f"Expected generated text, got {len(full_text)} chars"

        idle_events = [
            event.data
            for event in manager.get_events()
            if event.name == "voice_idle" and isinstance(event.data, VoiceIdleData)
        ]
        assert len(idle_events) >= 1
        assert idle_events[-1].voice == "jane"
    finally:
        await manager.close()


async def test_e2e_skill_instructions_inject_into_generation() -> None:
    """VoiceAgent with loaded skills and live provider generates with skill context."""
    tmp_path = Path("/tmp/kateto-e2e-skill-test")
    tmp_path.mkdir(parents=True, exist_ok=True)

    skill_path = tmp_path / "skills" / "orchestrator" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(
        "Orchestration skill: coordinate stakeholders and manage communication.",
        encoding="utf-8",
    )

    _write_reference(tmp_path, "jane")
    manager = PluginManager()
    provider = OpenAICompatibleProvider(
        model=OLLAMA_MODEL,
        endpoint=OLLAMA_ENDPOINT,
        api_key="sk-no-key-required",
    )
    profile = VoiceProfile(
        voice_id="jane",
        display_name="Jane",
        role=VoiceRole.ORCHESTRATOR,
        system_prompt="You are Jane, a project orchestrator.",
        relevance_terms=frozenset({"coordinate", "project"}),
    )
    voice = VoiceAgent(
        profile=profile,
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(skills=["orchestrator"]),
    )
    await manager.enable_plugin(voice)

    try:
        await manager.emit(
            "generate",
            GenerateData(prompt="How should I handle stakeholders?"),
            source="fixture",
        )
        await manager.wait_for_idle(timeout=60)

        chunks = [
            event.data
            for event in manager.get_events()
            if event.name == "text_chunk" and isinstance(event.data, TextChunk)
        ]
        full = "".join(c.text for c in chunks)
        assert len(full) > 10, f"Response too short: {full[:100]}"
        assert len(voice.loaded_skills) >= 1
        assert voice.loaded_skills[0].name == "orchestrator"
    finally:
        await manager.close()
