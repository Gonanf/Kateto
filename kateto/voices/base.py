from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import uuid4
from typing import Protocol, assert_never

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionDeveloperMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from pydantic import BaseModel

from kateto.core.config import VoiceSettings
from kateto.core.event import (
    EventEnvelope,
    GenerateData,
    InterruptData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VoiceIdleData,
    VoiceStatus,
    VoiceStatusData,
)
from kateto.core.plugin import EventHandler, Plugin
from kateto.providers import ChatMessage
from kateto.providers.agent import AgentProvider, ToolExecutor
from kateto.voices.memory import VoiceMemory
from kateto.voices.skills import LoadedSkill, load_skills


class VoiceRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    DELIVERY_ADVISOR = "delivery_advisor"
    AGILE_FACILITATOR = "agile_facilitator"


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    voice_id: str
    display_name: str
    role: VoiceRole
    system_prompt: str
    relevance_terms: frozenset[str]


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    voice_id: str
    reference_wav: Path
    messages: tuple[ChatMessage, ...]


class StreamingProvider(Protocol):
    def stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...


@dataclass(frozen=True, slots=True)
class ReferenceClipError(Exception):
    voice: str
    path: Path
    reason: str

    def __str__(self) -> str:
        return f"voice {self.voice} reference WAV {self.path}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ProviderStreamError(Exception):
    voice: str
    reason: str

    def __str__(self) -> str:
        return f"voice {self.voice} provider stream is invalid: {self.reason}"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProvider:
    model: str
    endpoint: str | None = None
    api_key: str | None = None

    def stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        return self._stream(request)

    async def _stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.endpoint)
        try:
            messages: list[ChatCompletionMessageParam] = []
            for message in request.messages:
                match message.role:
                    case "assistant":
                        messages.append(
                            ChatCompletionAssistantMessageParam(
                                role="assistant", content=message.content
                            )
                        )
                    case "developer":
                        messages.append(
                            ChatCompletionDeveloperMessageParam(
                                role="developer", content=message.content
                            )
                        )
                    case "system":
                        messages.append(
                            ChatCompletionSystemMessageParam(
                                role="system", content=message.content
                            )
                        )
                    case "user":
                        messages.append(
                            ChatCompletionUserMessageParam(
                                role="user", content=message.content
                            )
                        )
                    case unreachable:
                        assert_never(unreachable)
            stream = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content is not None:
                    yield content
        finally:
            await client.close()


class VoiceAgent(Plugin):
    def __init__(
        self,
        *,
        profile: VoiceProfile,
        config_dir: Path,
        provider: StreamingProvider,
        settings: VoiceSettings | None = None,
    ) -> None:
        super().__init__(
            profile.voice_id,
            capabilities=("voice", "agent", profile.role.value),
            streaming=False,
            batch_trigger="generate",
        )
        self.profile = profile
        self._config_dir = config_dir.resolve()
        self._provider = provider
        self._settings = VoiceSettings() if settings is None else settings
        self._memory = VoiceMemory.for_voice(
            config_dir=self._config_dir, voice=profile.voice_id
        )
        self._skills: tuple[LoadedSkill, ...] = ()
        self._generation_task: asyncio.Task[None] | None = None
        self._interrupted = False
        self._status: VoiceStatus | None = None
        self._agent_provider: AgentProvider | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tools: tuple[ChatCompletionToolParam, ...] = ()
        self._extra_tools: tuple[ChatCompletionToolParam, ...] = ()

    @property
    def role(self) -> VoiceRole:
        return self.profile.role

    @property
    def loaded_skills(self) -> tuple[LoadedSkill, ...]:
        return self._skills

    @property
    def agent_provider(self) -> AgentProvider | None:
        return self._agent_provider

    @property
    def tools(self) -> tuple[ChatCompletionToolParam, ...]:
        return self._tools

    def setup_agent(
        self,
        *,
        agent_provider: AgentProvider,
        tool_executor: ToolExecutor,
        extra_tools: tuple[ChatCompletionToolParam, ...] = (),
    ) -> None:
        from kateto.voices.tools import BUILTIN_TOOLS
        self._agent_provider = agent_provider
        self._tool_executor = tool_executor
        self._extra_tools = extra_tools
        self._tools = (*BUILTIN_TOOLS, *extra_tools)

    @property
    def reference_wav(self) -> Path:
        configured = self._settings.reference_audio or self._settings.reference_clip
        if configured is None:
            candidate = self._memory.store.path_for("reference.wav")
        else:
            candidate = (self._config_dir / configured).resolve()
            if not candidate.is_relative_to(self._memory.store.root):
                raise ReferenceClipError(
                    voice=self.name,
                    path=candidate,
                    reason="must stay inside the resolved voice directory",
                )
        if candidate.suffix.casefold() != ".wav":
            raise ReferenceClipError(
                voice=self.name, path=candidate, reason="must use a .wav extension"
            )
        if not candidate.is_file():
            raise ReferenceClipError(
                voice=self.name, path=candidate, reason="does not exist"
            )
        return candidate

    async def initialize(self) -> None:
        manager = self.manager
        if manager is None:
            return
        manager.register_event("text_chunk", TextChunk)
        manager.register_event("voice_idle", VoiceIdleData)
        manager.register_event("voice_status", VoiceStatusData)
        manager.register_event("tool_call", ToolCallData)
        manager.register_event("tool_result", ToolResultData)
        await self._memory.ensure_soul(self.profile.system_prompt)
        self._skills = load_skills(
            config_dir=self._config_dir, names=tuple(self._settings.skills)
        )

    async def enable(self) -> None:
        manager = self.manager
        if manager is not None and self._tool_executor is not None:
            from kateto.voices.tools import VoiceToolExecutor, BUILTIN_TOOLS, build_event_tools
            if isinstance(self._tool_executor, VoiceToolExecutor):
                self._tool_executor.set_manager(manager)
                event_tools = build_event_tools(manager)
                self._tools = (*BUILTIN_TOOLS, *event_tools, *self._extra_tools)
        await self._set_status(VoiceStatus.IDLE)

    async def disable(self) -> None:
        task = self._generation_task
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._generation_task = None
        await self._set_status(VoiceStatus.IDLE)

    async def _enqueue(
        self, envelope: EventEnvelope[BaseModel], handler: EventHandler
    ) -> None:
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case "transcription", TranscriptionData():
                await self._set_status(VoiceStatus.WAITING)
                await super()._enqueue(envelope, handler)
            case _:
                await super()._enqueue(envelope, handler)

    async def on_transcription(self, data: TranscriptionData) -> None:
        return None

    async def on_text_chunk(self, data: TextChunk) -> None:
        return None

    async def on_interrupt(self, data: InterruptData) -> None:
        task = self._generation_task
        if task is not None and not task.done():
            self._interrupted = True
            task.cancel()
        await self._set_status(VoiceStatus.IDLE)

    async def on_generate(self, data: GenerateData) -> None:
        prompt = self._prompt_for(data)
        # ponytail: is_relevant removed — classification plugin handles intent filtering now
        if prompt is None or not prompt.strip():
            return
        self._interrupted = False
        await self._set_status(VoiceStatus.THINKING)
        generation = asyncio.create_task(
            self._stream_response(prompt), name=f"kateto-voice-{self.name}"
        )
        self._generation_task = generation
        try:
            await generation
        except asyncio.CancelledError:
            if not self._interrupted:
                raise
        finally:
            if self._generation_task is generation:
                self._generation_task = None

    def _prompt_for(self, data: GenerateData) -> str | None:
        if data.prompt is not None:
            return data.prompt
        for event in reversed(self.batch_events):
            match event.data:
                case TranscriptionData(text=text):
                    return text
                case _:
                    continue
        return None

    async def _stream_response(self, prompt: str) -> None:
        if self._agent_provider is not None and self._tool_executor is not None:
            await self._agent_loop(prompt)
            return
        request = GenerationRequest(
            voice_id=self.name,
            reference_wav=self.reference_wav,
            messages=await self._messages_for(prompt),
        )
        open("/tmp/kateto_voice_debug.txt", "a").write(f"[{self.name}] _settings.stream={self._settings.stream} (type={type(self._settings).__name__})\n")
        if self._settings.stream:
            open("/tmp/kateto_voice_debug.txt", "a").write(f"[{self.name}] stream=true mode, emitting per token\n")
            previous: str | None = None
            sequence = 0
            async for token in self._provider.stream(request):
                if not isinstance(token, str) or not token:
                    raise ProviderStreamError(
                        voice=self.name, reason="token must be a non-empty string"
                    )
                if self._status is not VoiceStatus.TALKING:
                    await self._set_status(VoiceStatus.TALKING)
                if previous is not None:
                    await self._emit_chunk(previous, sequence, final=False)
                    sequence += 1
                previous = token
            if previous is not None:
                await self._emit_chunk(previous, sequence, final=True)
        else:
            open("/tmp/kateto_voice_debug.txt", "a").write(f"[{self.name}] stream=false mode, accumulating tokens...\n")
            tokens: list[str] = []
            async for token in self._provider.stream(request):
                if not isinstance(token, str) or not token:
                    raise ProviderStreamError(
                        voice=self.name, reason="token must be a non-empty string"
                    )
                if self._status is not VoiceStatus.TALKING:
                    await self._set_status(VoiceStatus.TALKING)
                tokens.append(token)
            if tokens:
                full = "".join(tokens)
                open("/tmp/kateto_voice_debug.txt", "a").write(f"[{self.name}] stream=false accumulated {len(tokens)} tokens -> {full!r}\n")
                await self._emit_chunk(full, 0, final=True)
        manager = self.manager
        if manager is not None:
            await manager.emit(
                "voice_idle", VoiceIdleData(voice=self.name), source=self.name
            )
        await self._set_status(VoiceStatus.IDLE)

    async def _agent_loop(self, prompt: str) -> None:
        provider = self._agent_provider
        executor = self._tool_executor
        if provider is None or executor is None:
            return
        chat_messages = await self._messages_for(prompt)
        messages: list[dict[str, object]] = [
            {"role": m.role, "content": m.content} for m in chat_messages
        ]
        max_iterations = 10
        for _ in range(max_iterations):
            if self._interrupted:
                break
            response = await provider.chat_with_tools(
                messages=messages,
                tools=self._tools,
            )
            if not response.tool_calls:
                if response.text:
                    await self._emit_chunk(response.text, 0, final=True)
                break
            messages.append(
                ChatCompletionAssistantMessageParam(
                    role="assistant",
                    content=response.text or None,
                    tool_calls=[
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in response.tool_calls
                    ],
                )
            )
            for tc in response.tool_calls:
                correlation_id = uuid4().hex
                manager = self.manager
                if manager is not None:
                    await manager.emit(
                        "tool_call",
                        ToolCallData(
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            correlation_id=correlation_id,
                            voice=self.name,
                        ),
                        source=self.name,
                    )
                try:
                    result = await executor.execute(tc.name, tc.arguments)
                    error = None
                except Exception as e:
                    result = ""
                    error = str(e)
                if manager is not None:
                    await manager.emit(
                        "tool_result",
                        ToolResultData(
                            correlation_id=correlation_id,
                            tool_name=tc.name,
                            result=result,
                            error=error,
                            voice=self.name,
                        ),
                        source=self.name,
                    )
                messages.append(
                    ChatCompletionToolMessageParam(
                        role="tool",
                        tool_call_id=tc.id,
                        content=result if error is None else f"Error: {error}",
                    )
                )
        manager = self.manager
        if manager is not None:
            await manager.emit(
                "voice_idle", VoiceIdleData(voice=self.name), source=self.name
            )
        await self._set_status(VoiceStatus.IDLE)

    async def _set_status(self, status: VoiceStatus) -> None:
        if self._status is status:
            return
        self._status = status
        manager = self.manager
        if manager is not None:
            await manager.emit(
                "voice_status",
                VoiceStatusData(voice=self.name, status=status),
                source=self.name,
            )

    async def _messages_for(self, prompt: str) -> tuple[ChatMessage, ...]:
        soul = await self._memory.read_soul()
        memories = await self._memory.read_memories()
        journal = await self._memory.read_journal()
        messages = [ChatMessage(role="system", content=self.profile.system_prompt)]
        if soul:
            messages.append(ChatMessage(role="system", content=soul))
        if memories:
            messages.append(ChatMessage(role="system", content=memories))
        if journal:
            messages.append(ChatMessage(role="system", content=journal))
        messages.extend(
            ChatMessage(role="system", content=skill.instructions)
            for skill in self._skills
        )
        context = self._untrusted_context()
        if context:
            messages.append(ChatMessage(role="user", content=context))
        messages.append(ChatMessage(role="user", content=prompt))
        return tuple(messages)

    def _untrusted_context(self) -> str:
        context: list[str] = []
        for event in self.batch_events:
            match event.data:
                case TranscriptionData(text=text):
                    context.append(text)
                case TextChunk(text=text, voice_id=voice_id) if voice_id != self.name:
                    context.append(text)
                case _:
                    continue
        return "\n".join(context)

    async def _emit_chunk(self, text: str, sequence: int, *, final: bool) -> None:
        manager = self.manager
        if manager is not None:
            await manager.emit(
                "text_chunk",
                TextChunk(
                    text=text, sequence=sequence, final=final, voice_id=self.name
                ),
                source=self.name,
            )
