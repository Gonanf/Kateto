from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from openai.types.chat import ChatCompletionToolParam

from kateto.providers.agent import AgentResponse, StreamToken, ToolCall


@dataclass(frozen=True, slots=True)
class FauxResponseStep:
    """One scripted LLM turn for the FauxProvider.

    Yields `chunks` as streamed text tokens (each preceded by `delay`
    seconds), then an AgentResponse carrying `tool_calls` when present.
    `stop_reason` models the model's finish_reason ("length" simulates a
    truncated response whose tool args must not run). `error` raises instead
    of responding (simulated provider failure).
    """

    chunks: tuple[str, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None
    delay: float = 0.0
    error: str | None = None


class FauxProvider:
    """Deterministic offline LLM provider driven by a script of steps.

    Each `chat_with_tools[_stream]` call consumes the next script step, so a
    tool loop replays turn by turn. Records every call's messages for
    assertions (e.g. the error tool messages the guard sends back).
    """

    def __init__(self, script: Sequence[FauxResponseStep], *, stream: bool = True) -> None:
        self._steps = list(script)
        self._index = 0
        self.stream = stream
        self.calls = 0
        self.requests: list[list[dict[str, Any]]] = []
        self.tools_seen: list[tuple[ChatCompletionToolParam, ...]] = []

    def _next_step(self) -> FauxResponseStep:
        if self._index >= len(self._steps):
            return FauxResponseStep()
        step = self._steps[self._index]
        self._index += 1
        return step

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AgentResponse:
        self.calls += 1
        self.requests.append(messages)
        self.tools_seen.append(tools)
        step = self._next_step()
        if step.error is not None:
            raise RuntimeError(step.error)
        if step.delay:
            await asyncio.sleep(step.delay)
        return AgentResponse(
            text="".join(step.chunks),
            tool_calls=step.tool_calls,
            stop_reason=step.stop_reason,
        )

    async def chat_with_tools_stream(
        self,
        messages: list[dict[str, Any]],
        tools: tuple[ChatCompletionToolParam, ...],
    ) -> AsyncIterator[StreamToken | AgentResponse]:
        self.calls += 1
        self.requests.append(messages)
        self.tools_seen.append(tools)
        step = self._next_step()
        if step.error is not None:
            raise RuntimeError(step.error)
        for chunk in step.chunks:
            if step.delay:
                await asyncio.sleep(step.delay)
            yield StreamToken(text=chunk)
        if step.tool_calls:
            yield AgentResponse(
                text="",
                tool_calls=step.tool_calls,
                stop_reason=step.stop_reason,
            )