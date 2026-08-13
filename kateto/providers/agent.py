from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionToolParam


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    # finish_reason of the underlying completion ("length" => truncated turn)
    stop_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StreamToken:
    text: str


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


class OpenAIAgentProvider:
    def __init__(
        self,
        model: str,
        endpoint: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 4096,
        retries: int | None = None,
        timeout: float | None = None,
        session_headers: Mapping[str, str] | None = None,
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key or "sk-no-key-required",
            base_url=endpoint,
            max_retries=retries if retries is not None else 2,
            timeout=timeout if timeout is not None else 600,
        )
        self._max_tokens = max_tokens
        self._session_headers = dict(session_headers or {})

    def _base_kwargs(self, *, stream: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
        }
        if stream:
            kwargs["stream"] = True
        if self._session_headers:
            kwargs["extra_headers"] = dict(self._session_headers)
        return kwargs

    async def chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse:
        kwargs = self._base_kwargs(stream=False)
        kwargs["messages"] = messages
        if tools:
            kwargs["tools"] = list(tools)
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        finish_reason = getattr(choice, "finish_reason", None)
        if message.tool_calls:
            tool_calls = tuple(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=_parse_json(tc.function.arguments),
                )
                for tc in message.tool_calls
            )
            return AgentResponse(
                text=message.content or "",
                tool_calls=tool_calls,
                stop_reason=finish_reason,
            )
        return AgentResponse(text=message.content or "", stop_reason=finish_reason)

    async def chat_with_tools_stream(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        kwargs = self._base_kwargs(stream=True)
        kwargs["messages"] = messages
        if tools:
            kwargs["tools"] = list(tools)
        stream = await self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tool_calls_buf: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                text_parts.append(delta.content)
                yield StreamToken(text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    index = tc.index
                    if index not in tool_calls_buf:
                        tool_calls_buf[index] = {"id": tc.id or "", "name": tc.function.name or "", "arguments": ""}
                    if tc.function and tc.function.arguments:
                        tool_calls_buf[index]["arguments"] += tc.function.arguments
            finish_reason = chunk.choices[0].finish_reason

        if tool_calls_buf:
            yield AgentResponse(
                text="".join(text_parts),
                tool_calls=tuple(
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=_parse_json(tc["arguments"]),
                    )
                    for tc in sorted(tool_calls_buf.values(), key=lambda x: x["id"])
                ),
                stop_reason=finish_reason,
            )


def _parse_json(raw: str) -> dict[str, Any]:
    import json
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {"raw": raw}


class HermesProvider(OpenAIAgentProvider):
    """OpenAI-compatible provider for a Hermes harness that manages
    conversations itself and requires conversation_id in the request body."""

    def __init__(
        self,
        conversation_id: str,
        *,
        model: str,
        endpoint: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 4096,
        retries: int | None = None,
        timeout: float | None = None,
        session_headers: Mapping[str, str] | None = None,
        manage_tools: bool = False,
    ) -> None:
        super().__init__(
            model=model,
            endpoint=endpoint,
            api_key=api_key,
            max_tokens=max_tokens,
            retries=retries,
            timeout=timeout,
            session_headers=session_headers,
        )
        self._conversation_id = conversation_id
        self._manage_tools = manage_tools

    def _base_kwargs(self, *, stream: bool) -> dict[str, Any]:
        kwargs = super()._base_kwargs(stream=stream)
        kwargs["extra_body"] = {"conversation_id": self._conversation_id}
        return kwargs

    async def chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse:
        effective_tools = tools if self._manage_tools else ()
        return await super().chat_with_tools(messages, effective_tools)

    async def chat_with_tools_stream(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        effective_tools = tools if self._manage_tools else ()
        async for token in super().chat_with_tools_stream(messages, effective_tools):
            yield token
