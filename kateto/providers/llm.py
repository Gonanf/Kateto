from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import TextChunk

from ._http import HttpProvider, SseEvent, configured_endpoint, iter_sse_events
from ._models import (
    ChatMessage,
    ChatRequest,
    ChatStreamResponse,
    ResponseDelta,
    ResponseEventType,
    ResponseInputMessage,
    ResponseInputText,
    ResponsesRequest,
)
from .errors import MalformedUpstreamResponse


class LlamaCppChatProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = "/v1/chat/completions",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            provider_name="llama.cpp chat completions",
            endpoint=configured_endpoint(settings, provider="llama.cpp", endpoint=endpoint),
            client=client,
            timeout_s=timeout_s,
        )
        self._model = settings.model
        self._path = path

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[TextChunk]:
        request = ChatRequest(model=self._model, messages=tuple(messages))
        sequence = 0
        completed = False
        async with self._client_or_raise().stream(
            "POST",
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response):
                if event.data == "[DONE]":
                    completed = True
                    break
                try:
                    payload = ChatStreamResponse.model_validate_json(event.data)
                except ValidationError as error:
                    raise MalformedUpstreamResponse(provider="llama.cpp", reason="expected chat completion SSE") from error
                text = payload.choices[0].delta.content
                if text is not None:
                    yield TextChunk(text=text, sequence=sequence)
                    sequence += 1
        if not completed:
            raise MalformedUpstreamResponse(provider="llama.cpp", reason="stream ended without [DONE]")
        yield TextChunk(text="", sequence=sequence, final=True)


class OpenAIResponsesProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = "/v1/responses",
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else None
        super().__init__(
            provider_name="openai responses",
            endpoint=configured_endpoint(settings, provider="openai responses", endpoint=endpoint),
            client=client,
            timeout_s=timeout_s,
            headers=headers,
        )
        self._model = settings.model
        self._path = path

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[TextChunk]:
        request = ResponsesRequest(
            model=self._model,
            input=tuple(
                ResponseInputMessage(
                    role=message.role,
                    content=(ResponseInputText(text=message.content),),
                )
                for message in messages
            ),
        )
        sequence = 0
        completed = False
        async with self._client_or_raise().stream(
            "POST",
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        ) as response:
            response.raise_for_status()
            async for event in iter_sse_events(response):
                if event.data == "[DONE]":
                    completed = True
                    break
                event_type = _event_type(event)
                match event_type:
                    case "response.output_text.delta":
                        try:
                            payload = ResponseDelta.model_validate_json(event.data)
                        except ValidationError as error:
                            raise MalformedUpstreamResponse(
                                provider="openai responses",
                                reason="expected response output text delta",
                            ) from error
                        yield TextChunk(text=payload.delta, sequence=sequence)
                        sequence += 1
                    case "response.completed":
                        completed = True
                        break
                    case _:
                        continue
        if not completed:
            raise MalformedUpstreamResponse(provider="openai responses", reason="stream ended without completion")
        yield TextChunk(text="", sequence=sequence, final=True)


def _event_type(event: SseEvent) -> str:
    if event.event is not None:
        return event.event
    try:
        return ResponseEventType.model_validate_json(event.data).type
    except ValidationError as error:
        raise MalformedUpstreamResponse(provider="openai responses", reason="expected typed SSE event") from error
