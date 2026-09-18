"""Voice LLM wire params: max_tokens verbatim + reasoning_effort (spec 2026-09-18)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kateto.providers import ChatMessage
from kateto.voices.base import GenerationRequest, OpenAICompatibleProvider, _openai_client


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


def make_fake_client(captured: dict[str, Any]) -> type:
    class FakeCompletions:
        async def create(self, **kwargs: object) -> FakeStream:
            captured.update(kwargs)
            return FakeStream((FakeChunk(),))

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

        async def close(self) -> None:
            return None

    return FakeClient


def _request() -> GenerationRequest:
    return GenerationRequest(
        voice_id="jane",
        reference_wav=Path("/tmp/x.wav"),
        messages=(ChatMessage(role="user", content="hi"),),
    )


async def _stream(provider: OpenAICompatibleProvider) -> list[str]:
    return [t async for t in provider.stream(_request())]


@pytest.mark.asyncio
async def test_configured_max_tokens_reaches_payload_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: voz con max_tokens 4096 (cap silencioso a 384 antes del fix).
    captured: dict[str, Any] = {}
    _openai_client.cache_clear()
    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", make_fake_client(captured))
    provider = OpenAICompatibleProvider(
        model="voice", endpoint="http://127.0.0.1:9911/v1", max_tokens=4096
    )

    # When: se stremea un turno.
    tokens = await _stream(provider)

    # Then: el payload lleva 4096 verbatim.
    assert tokens == ["ok"]
    assert captured["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_max_tokens_defaults_to_256(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: voz sin max_tokens configurado.
    captured: dict[str, Any] = {}
    _openai_client.cache_clear()
    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", make_fake_client(captured))
    provider = OpenAICompatibleProvider(model="voice", endpoint="http://127.0.0.1:9912/v1")

    # When: se stremea un turno.
    await _stream(provider)

    # Then: default 256.
    assert captured["max_tokens"] == 256


@pytest.mark.asyncio
async def test_thinking_false_sends_reasoning_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: thinking=false sin reasoning_effort explícito.
    captured: dict[str, Any] = {}
    _openai_client.cache_clear()
    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", make_fake_client(captured))
    provider = OpenAICompatibleProvider(
        model="voice", endpoint="http://127.0.0.1:9913/v1", thinking=False
    )

    # When: se stremea un turno.
    await _stream(provider)

    # Then: el proveedor recibe reasoning_effort=none por extra_body.
    assert captured["extra_body"] == {"reasoning_effort": "none"}


@pytest.mark.asyncio
async def test_thinking_true_sends_no_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: thinking=true (default) sin reasoning_effort explícito.
    captured: dict[str, Any] = {}
    _openai_client.cache_clear()
    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", make_fake_client(captured))
    provider = OpenAICompatibleProvider(
        model="voice", endpoint="http://127.0.0.1:9914/v1", thinking=True
    )

    # When: se stremea un turno.
    await _stream(provider)

    # Then: el campo no se manda (decide el modelo).
    assert captured.get("extra_body") is None


@pytest.mark.asyncio
async def test_explicit_reasoning_effort_wins_over_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: reasoning_effort explícito con thinking=false.
    captured: dict[str, Any] = {}
    _openai_client.cache_clear()
    monkeypatch.setattr("kateto.voices.base.AsyncOpenAI", make_fake_client(captured))
    provider = OpenAICompatibleProvider(
        model="voice",
        endpoint="http://127.0.0.1:9915/v1",
        thinking=False,
        reasoning_effort="low",
    )

    # When: se stremea un turno.
    await _stream(provider)

    # Then: va tal cual, sin normalizar a none.
    assert captured["extra_body"] == {"reasoning_effort": "low"}


@pytest.mark.asyncio
async def test_tools_path_still_builds_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: el path pydantic-ai con tools (OpenAI + Hermes).
    from kateto.providers.agent import HermesProvider, OpenAIAgentProvider

    captured: dict[str, Any] = {}

    class FakeCompletions:
        async def create(self, **kwargs: object) -> Any:
            captured.update(kwargs)
            message = type("M", (), {"content": "hi", "tool_calls": None})()
            choice = type("C", (), {"message": message, "finish_reason": "stop"})()
            return type("R", (), {"choices": (choice,)})()

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr("kateto.providers.agent.AsyncOpenAI", FakeClient)

    # When: chat sin tools por el provider base.
    provider = OpenAIAgentProvider(
        model="voice", endpoint="http://127.0.0.1:9916/v1", max_tokens=4096
    )
    response = await provider.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}], tools=()
    )

    # Then: responde y el max_tokens va verbatim (sin cap 384).
    assert response.text == "hi"
    assert captured["max_tokens"] == 4096

    # When: mismo request por Hermes.
    captured.clear()
    hermes = HermesProvider(
        conversation_id="c1",
        model="voice",
        endpoint="http://127.0.0.1:9916/v1",
        max_tokens=4096,
    )
    response = await hermes.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}], tools=()
    )

    # Then: conversation_id sobrevive en extra_body y max_tokens verbatim.
    assert response.text == "hi"
    assert captured["extra_body"] == {"conversation_id": "c1"}
    assert captured["max_tokens"] == 4096
