from __future__ import annotations

from collections.abc import AsyncIterator
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
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key or "sk-no-key-required", base_url=endpoint)
        self._max_tokens = max_tokens

    async def chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
        }
        if tools:
            kwargs["tools"] = list(tools)
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        if message.tool_calls:
            tool_calls = tuple(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=_parse_json(tc.function.arguments),
                )
                for tc in message.tool_calls
            )
            return AgentResponse(text=message.content or "", tool_calls=tool_calls)
        return AgentResponse(text=message.content or "")

    async def chat_with_tools_stream(
        self,
        messages: list[dict[str, object]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "stream": True,
        }
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
