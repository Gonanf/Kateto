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
    VOLATILE_MARKER,
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
            role=VoiceRole.SITUATIONAL_ABSURD,
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
            role=VoiceRole.SITUATIONAL_ABSURD,
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
        # Then: el journal viaja DENTRO del turno de usuario, después del prompt
        # y separado por el marcador (2026-09-23). Un system intercalado se
        # descartaría en el camino pydantic (filtro a roles assistant/user) y
        # algunos gateways remotos reordenan system messages posteriores.
        last = messages[-1]
        assert last.role == "user"
        assert last.content.startswith("Hi")
        assert VOLATILE_MARKER in last.content
        assert "voice_idle" in last.content
        assert last.content.index("voice_idle") > last.content.index(VOLATILE_MARKER)
        assert not any(m.role == "system" and "voice_idle" in m.content for m in messages)
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
            role=VoiceRole.SITUATIONAL_ABSURD,
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


def test_assemble_messages_embeds_volatile_in_last_user_turn() -> None:
    history = (ChatMessage(role="user", content="prev"),)
    messages = assemble_messages(
        stable="STABLE",
        history=history,
        volatile="VOLATILE",
        prompt="Now",
    )
    assert [m.role for m in messages] == ["system", "user", "user"]
    assert messages[0].content == "STABLE"
    assert messages[1].content == "prev"
    last = messages[-1].content
    assert last.startswith("Now")
    assert "VOLATILE" in last
    assert last.index("VOLATILE") > last.index(VOLATILE_MARKER)


def test_assemble_messages_bare_prompt_without_volatile() -> None:
    messages = assemble_messages(
        stable="STABLE",
        history=(),
        volatile=None,
        prompt="Now",
    )
    assert [m.role for m in messages] == ["system", "user"]
    assert messages[-1].content == "Now"


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


def test_volatile_block_caps_journal_lines() -> None:
    journal = "line1\n\nline2\nline3\n"
    assert volatile_block(workflow_system=None, journal=journal) == journal
    assert volatile_block(workflow_system=None, journal=journal, journal_max_lines=2) == "line2\nline3"
    assert volatile_block(workflow_system=None, journal=journal, journal_max_lines=0) is None
    assert volatile_block(workflow_system=None, journal=None, journal_max_lines=5) is None
    assert volatile_block(workflow_system=None, journal=journal, journal_max_lines=100) == "line1\nline2\nline3"


@pytest.mark.asyncio
async def test_journal_cap_flows_from_voice_settings(tmp_path: Path) -> None:
    # Given: un journal de 3 líneas y una voz con journal_max_lines=2.
    _reference(tmp_path)
    (tmp_path / "voices" / "jane" / "JOURNAL.md").write_text(
        "line1\nline2\nline3\n", encoding="utf-8"
    )
    provider = RecordingProvider()
    voice = VoiceAgent(
        profile=VoiceProfile(
            voice_id="jane",
            display_name="Jane",
            role=VoiceRole.SITUATIONAL_ABSURD,
            system_prompt="system",
            relevance_terms=frozenset(),
        ),
        config_dir=tmp_path,
        provider=provider,
        settings=VoiceSettings(journal_max_lines=2),
    )
    manager = PluginManager()
    await manager.enable_plugin(voice)

    try:
        # When: se arma el turno.
        await manager.emit("generate", GenerateData(prompt="Hi"), source="fixture")
        await manager.wait_for_idle()

        # Then: el journal llega capado a las últimas 2 líneas, sin tocar el archivo.
        last = provider.requests[0].messages[-1].content
        assert "line1" not in last
        assert "line2" in last and "line3" in last
        assert (tmp_path / "voices" / "jane" / "JOURNAL.md").read_text() == "line1\nline2\nline3\n"
    finally:
        await manager.close()


def _reference(config_dir: Path) -> None:
    path = config_dir / "voices" / "jane" / "reference.wav"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"RIFFfixtureWAVE")


def test_stable_prompt_puts_voice_independent_head_first() -> None:
    import os

    prompt_jane = stable_prompt(
        soul="You are Jane, the lead.",
        profile_system_prompt="You are Jane, the lead.",
        response_language="es_ar",
        workflow_block=None,
        mcp_block="[MCP Tools: system]",
        delegation_block="[Delegation Guidance]",
        boson_block=None,
        skills=(),
        memories=None,
    )
    prompt_doktor = stable_prompt(
        soul="You are Doktor, the pedant.",
        profile_system_prompt="You are Doktor, the pedant.",
        response_language="es_ar",
        workflow_block=None,
        mcp_block="[MCP Tools: system]",
        delegation_block="[Delegation Guidance]",
        boson_block=None,
        skills=(),
        memories=None,
    )

    common = os.path.commonprefix([prompt_jane, prompt_doktor])
    assert "Always respond in the project's configured language: es_ar" in common
    assert "[MCP Tools: system]" in common
    assert "[Delegation Guidance]" in common
    assert "You are Jane" not in common
    assert "You are Doktor" not in common
    assert prompt_jane[len(common):].startswith("Jane")
    assert prompt_doktor[len(common):].startswith("Doktor")


def test_stable_prompt_content_is_order_only() -> None:
    class DummySkill:
        def __init__(self, instructions: str) -> None:
            self.instructions = instructions

    expected_blocks = [
        "Always respond in the project's configured language: es_ar. This instruction overrides the language of the user input.",
        "## MCP Tools Block",
        "## Delegation Block",
        "You are Jane, the lead.",
        "A customized soul file.",
        "## Workflow Block",
        "## Boson Block",
        "## Skill 1 instructions",
        "## Durable memories",
        "Voice turn constraint: Always speak to the user in 1-2 short natural sentences (under 40 words). Never use lists, bullet points, headers, or markdown formatting.",
    ]

    result = stable_prompt(
        soul=expected_blocks[4],
        profile_system_prompt=expected_blocks[3],
        response_language="es_ar",
        workflow_block=expected_blocks[5],
        mcp_block=expected_blocks[1],
        delegation_block=expected_blocks[2],
        boson_block=expected_blocks[6],
        skills=(DummySkill(expected_blocks[7]),),
        memories=expected_blocks[8],
    )

    for block in expected_blocks:
        assert block in result
        assert result.count(block) == 1

    assert result == "\n\n".join(expected_blocks)


def test_voice_turn_constraint_stays_last() -> None:
    brevity = (
        "Voice turn constraint: Always speak to the user in 1-2 short natural sentences"
        " (under 40 words). Never use lists, bullet points, headers, or markdown formatting."
    )
    prompt = stable_prompt(
        soul="Custom soul",
        profile_system_prompt="Custom profile",
        response_language="es_ar",
        workflow_block="Workflow",
        mcp_block="MCP",
        delegation_block="Delegation",
        boson_block="Boson",
        skills=(),
        memories="Memories",
    )
    assert prompt.endswith(brevity)
