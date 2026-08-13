from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from kateto.providers.boson_tts import _httpx_client
from kateto.voices.base import PhraseSegmenter, VoiceEventStream, _openai_client


@pytest.mark.asyncio
async def test_phrase_segmenter_cuts_only_on_delimiters() -> None:
    # Given: a fresh segmenter fed realistic token chunks.
    segmenter = PhraseSegmenter()
    # When: tokens arrive without a delimiter, no phrase forms.
    assert segmenter.feed("Hola") == []
    # Then: ". " (delimiter + space) triggers a cut.
    assert segmenter.feed(". ") == ["Hola. "]
    assert segmenter.feed("¿Qué") == []
    assert segmenter.feed(" tal?") == [" ¿Qué tal?"]
    # And: the leftover buffers until flush().
    assert segmenter.feed("Bien") == []
    assert segmenter.flush() == "Bien"
    assert segmenter.flush() is None


@pytest.mark.asyncio
async def test_phrase_segmenter_cuts_on_max_tokens() -> None:
    # Given: a segmenter with a tiny max_tokens ceiling.
    segmenter = PhraseSegmenter(max_tokens=2)
    # When: three delimiter-free tokens are fed.
    assert segmenter.feed("a") == []
    # Then: the second feed crosses the ceiling and cuts.
    assert segmenter.feed("b") == ["ab"]
    assert segmenter.feed("c") == []
    assert segmenter.flush() == "c"


@pytest.mark.asyncio
async def test_voice_event_stream_resolves_final_message_with_usage() -> None:
    # Given: a stream wrapping a three-token generator.
    async def tokens() -> AsyncIterator[str]:
        yield "Hola"
        yield " mundo"
        yield "!"

    stream = VoiceEventStream(tokens())
    # When: the stream is fully iterated and metadata is set.
    deltas = [token async for token in stream]
    assert deltas == ["Hola", " mundo", "!"]
    stream.set_meta(usage={"total_tokens": 5}, stop_reason="stop")
    # Then: the final message resolves with accumulated text and metadata.
    msg = await stream.final_message()
    assert msg.text == "Hola mundo!"
    assert msg.usage == {"total_tokens": 5}
    assert msg.stop_reason == "stop"


@pytest.mark.asyncio
async def test_voice_event_stream_resolves_after_exhaustion_without_manual_finish() -> None:
    # Given: a one-token generator.
    async def tokens() -> AsyncIterator[str]:
        yield "only"

    stream = VoiceEventStream(tokens())
    # When: iteration finishes before final_message() is ever requested.
    collected = [token async for token in stream]
    assert collected == ["only"]
    # Then: the Future is already resolved with the accumulated text.
    msg = await stream.final_message()
    assert msg.text == "only"
    assert msg.usage is None
    assert msg.stop_reason is None


@pytest.mark.asyncio
async def test_openai_client_cache_reuses_client_per_endpoint() -> None:
    # Given: the cached OpenAI client factory.
    # Then: same endpoint+key reuses the client; different endpoint or key does not.
    assert _openai_client("http://a", "k") is _openai_client("http://a", "k")
    assert _openai_client("http://a", "k") is not _openai_client("http://b", "k")
    assert _openai_client("http://a", "k") is not _openai_client("http://a", "other")


@pytest.mark.asyncio
async def test_boson_httpx_client_cache_reuses_client_per_endpoint() -> None:
    # Given: the cached httpx client factory.
    # Then: same endpoint reuses the client; a different endpoint does not.
    assert _httpx_client("http://a") is _httpx_client("http://a")
    assert _httpx_client("http://a") is not _httpx_client("http://b")