from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)

from kateto.providers._models import ChatMessage


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


class ToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> str: ...


class AgentProvider(Protocol):
    async def chat_with_tools(
        self,
        messages: tuple[ChatMessage, ...],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse: ...


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
        messages: tuple[ChatMessage, ...],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse:
        oai_messages = _convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": oai_messages,
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


def _convert_messages(messages: tuple[ChatMessage, ...]) -> list[ChatCompletionMessageParam]:
    result: list[ChatCompletionMessageParam] = []
    for message in messages:
        match message.role:
            case "assistant":
                result.append(ChatCompletionAssistantMessageParam(role="assistant", content=message.content))
            case "developer":
                result.append(ChatCompletionDeveloperMessageParam(role="developer", content=message.content))
            case "system":
                result.append(ChatCompletionSystemMessageParam(role="system", content=message.content))
            case "user":
                result.append(ChatCompletionUserMessageParam(role="user", content=message.content))
    return result


def _parse_json(raw: str) -> dict[str, Any]:
    import json
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return {"raw": raw}
