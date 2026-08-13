"""Tests for the stable-prompt + prompt-caching feature (spec 2026-08-13)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from kateto.core import PluginManager
from kateto.core.config import VoiceSettings
from kateto.core.event import GenerateData
from kateto.providers import ChatMessage
from kateto.voices.base import (
    GenerationRequest,
    OpenAICompatibleProvider,
    VoiceAgent,
    VoiceProfile,
    VoiceRole,
)
from kateto.voices.context import (
    assemble_messages,
    prompt_cache_key,
    session_headers,
    stable_prompt,
    volatile_block,
)


class RecordingProvider:
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        self.requests.append(request)
        return self._tokens()

    async def _tokens(self) -> AsyncIterator[str]:
        yield "reply"


@pytest.mark.asyncio
async def test_stable_prompt_is_frozen_across_turns(tmp_path: Path) -> None:
    # Given: a Jane voice with a fresh config dir (no SOUL yet).
    _reference(tmp_path)
    provider = RecordingProvider()
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="You are Jane, the lead.",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: two independent turns hit the voice.
        await manager.emit("generate", GenerateData(prompt="First turn"), source="fixture")
        await manager.wait_for_idle()
        first = provider.requests[0]
        await manager.emit("generate", GenerateData(prompt="Second turn"), source="fixture")
        await manager.wait_for_idle()
        second = provider.requests[1]

        # Then: both requests reuse the same stable system prefix, byte-for-byte.
        first_stable = first.messages[0].content
        second_stable = second.messages[0].content
        assert first_stable == second_stable
        assert "You are Jane, the lead." in first_stable
        # And the volatile block lands at the END, after the user prompt.
        assert first.messages[-1].role == "user"
        assert second.messages[-1].role == "user"
        assert second.messages[-1].content == "Second turn"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_volatile_context_is_appended_not_inlined(tmp_path: Path) -> None:
    # Given: a voice that writes a journal so the volatile block is non-empty.
    _reference(tmp_path)
    (tmp_path / "voices" / "jane" / "JOURNAL.md").write_text(
        "- [auto] voice_idle at 2026-08-13T12:00:00Z\n", encoding="utf-8"
    )
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
        await manager.emit("generate", GenerateData(prompt="Hi"), source="fixture")
        await manager.wait_for_idle()

        messages = provider.requests[0].messages
        # Then: the journal text appears in a dedicated system message AFTER the user prompt.
        volatile = next(
            m for m in messages if m.role == "system" and "voice_idle" in m.content
        )
        assert messages.index(volatile) == len(messages) - 2
        assert messages[-1].role == "user"
    finally:
        await manager.close()


def test_prompt_cache_key_is_fixed_per_voice() -> None:
    assert prompt_cache_key("Jane") == "kateto-voice-jane"
    assert prompt_cache_key("jane") == "kateto-voice-jane"


def test_session_headers_carry_session_id_and_affinity() -> None:
    headers = session_headers("jane", "abc123")
    assert headers["x-session-id"] == "abc123"
    assert headers["x-session-affinity"] == "kateto-voice-jane"


def test_voice_session_headers_are_stable_across_turns(tmp_path: Path) -> None:
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.ORCHESTRATOR,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=RecordingProvider(),
        settings=VoiceSettings(),
    )
    assert voice.session_headers["x-session-id"] == voice.session_id
    assert voice.session_headers["x-session-affinity"] == "kateto-voice-jane"
    assert voice.prompt_cache_key == "kateto-voice-jane"


@pytest.mark.asyncio
async def test_openai_compatible_provider_sends_session_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    create_kwargs: dict[str, Any] = {}

    class FakeChunk:
        choices = (type("C", (), {"delta": type("D", (), {"content": "ok"})()})(),)

    class FakeStream:
        def __init__(self, chunks: tuple[FakeChunk, ...]) -> None:
            self._chunks = iter(chunks)

        def __aiter__(self) -> "FakeStream":
            return self

        async def __anext__(self) -> FakeChunk:
            try:
                return next(self._chunks)
            except StopIteration:
                raise StopAsyncIteration

    class FakeCompletions:
        async def create(self, **kwargs: object) -> FakeStream:
            create_kwargs.update(kwargs)
            return FakeStream((FakeChunk(),))

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            create_kwargs["__client__"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def close(self) -> None:
            return None

    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", FakeClient)
    provider = OpenAICompatibleProvider(
        model="voice",
        endpoint="http://127.0.0.1:9999/v1",
        max_tokens=512,
        session_headers={"x-session-id": "s1", "x-session-affinity": "kateto-voice-jane"},
    )
    tokens = [t async for t in provider.stream(GenerationRequest(voice_id="jane", reference_wav=Path("/tmp/x.wav"), messages=(ChatMessage(role="user", content="hi"),)))]
    assert tokens == ["ok"]
    assert create_kwargs["max_tokens"] == 512
    assert create_kwargs["extra_headers"] == {
        "x-session-id": "s1",
        "x-session-affinity": "kateto-voice-jane",
    }
    client_kwargs = create_kwargs["__client__"]
    assert client_kwargs["max_retries"] == 2
    assert client_kwargs["timeout"] == 600


def test_assemble_messages_orders_stable_history_volatile_user() -> None:
    history = (ChatMessage(role="user", content="prev"),)
    messages = assemble_messages(
        stable="STABLE",
        history=history,
        volatile="VOLATILE",
        prompt="Now",
    )
    assert [m.role for m in messages] == ["system", "user", "system", "user"]
    assert messages[0].content == "STABLE"
    assert messages[2].content == "VOLATILE"
    assert messages[3].content == "Now"


def test_stable_prompt_skips_soul_when_duplicate_of_profile() -> None:
    prompt = stable_prompt(
        soul="You are Jane, the lead.",
        profile_system_prompt="You are Jane, the lead.",
        response_language=None,
        workflow_block=None,
        mcp_block=None,
        delegation_block=None,
        boson_block=None,
        skills=(),
        memories=None,
    )
    assert prompt.count("You are Jane, the lead.") == 1


def test_volatile_block_none_without_inputs() -> None:
    assert volatile_block(workflow_system=None) is None


def _reference(config_dir: Path) -> None:
    path = config_dir / "voices" / "jane" / "reference.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFFfixtureWAVE")
