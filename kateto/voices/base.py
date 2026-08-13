from __future__ import annotations

import asyncio
import inspect
import json
from loguru import logger
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import uuid4
from typing import TYPE_CHECKING, Any, Protocol, assert_never

if TYPE_CHECKING:
    from kateto.plugins.system.turn_gate import Decision, TurnGate

log = logger

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
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from kateto.core.config import VoiceSettings
from kateto.core.event import (
    EventEnvelope,
    EventModel,
    GENERATE_REQUEST_MAX_DEPTH,
    GenerateData,
    GenerateRequestData,
    InterruptData,
    SpeakRequestData,
    TextChunk,
    ToolCallData,
    ToolResultData,
    TranscriptionData,
    VoiceIdleData,
    VoiceRequestData,
    VoiceStatus,
    VoiceStatusData,
    WorkflowCheckpointFailData,
    WorkflowCompletedData,
    WorkflowPhaseCompleteData,
    WorkflowPhaseStartData,
    WorkflowRunData,
    WorkflowStartedData,
    WorkflowStopData,
)
from kateto.core.plugin import EventHandler, Plugin
from kateto.core.workflow import WorkflowCatalog, WorkflowNotFoundError
from kateto.providers import ChatMessage
from kateto.providers.agent import AgentResponse, OpenAIAgentProvider, StreamToken, ToolCall, ToolExecutor
from kateto.voices.memory import VoiceMemory
from kateto.voices.skills import LoadedSkill, load_skills

# Data plane: direct channels bypassing the event bus for streaming data
_PIPELINES: dict[str, AudioPipeline] = {}


@dataclass
class AudioPipeline:
    """Direct data channel for streaming tokens and PCM between voice, TTS, and player."""
    token_queue: asyncio.Queue[str | None] = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    pcm_queue: asyncio.Queue[bytes | None] = field(default_factory=lambda: asyncio.Queue(maxsize=32))


def _remove_pipeline(voice_id: str) -> None:
    _PIPELINES.pop(voice_id, None)


def get_pipeline(voice_id: str) -> AudioPipeline | None:
    return _PIPELINES.get(voice_id)


class VoiceRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    DELIVERY_ADVISOR = "delivery_advisor"
    AGILE_FACILITATOR = "agile_facilitator"
    PROJECT_MANAGER = "project_manager"
    ADVERSARY = "adversary"


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    voice_id: str
    display_name: str
    role: VoiceRole
    system_prompt: str
    relevance_terms: frozenset[str]
    capabilities: tuple[str, ...] = ()
    depts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    voice_id: str
    reference_wav: Path
    messages: tuple[ChatMessage, ...]


class VoiceProvider(Protocol):
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


def _to_pydantic_messages(
    messages: tuple[ChatMessage, ...],
) -> list[ModelRequest | ModelResponse]:
    # pydantic-ai message_history needs Message objects (they carry .conversation_id);
    # raw dicts crash in resolve_conversation_id — see bug 38.
    result: list[ModelRequest | ModelResponse] = []
    for message in messages:
        if message.role == "assistant":
            result.append(ModelResponse(parts=[TextPart(content=message.content)]))
        elif message.role in ("system", "developer"):
            result.append(ModelRequest(parts=[SystemPromptPart(content=message.content)]))
        else:
            result.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
    return result


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
    immediate_events = frozenset({"interrupt", "speak", "generate_request"})

    def __init__(
        self,
        *,
        profile: VoiceProfile,
        config_dir: Path,
        provider: VoiceProvider,
        settings: VoiceSettings | None = None,
        response_language: str | None = None,
    ) -> None:
        super().__init__(
            profile.voice_id,
            capabilities=("voice", "agent", profile.role.value),
            depts=profile.depts,
            streaming=False,
            batch_trigger="generate",
        )
        self.profile = profile
        self._config_dir = config_dir.resolve()
        self._provider = provider
        self._settings = VoiceSettings() if settings is None else settings
        self._response_language = response_language.strip() if response_language else None
        self._memory = VoiceMemory.for_voice(
            config_dir=self._config_dir, voice=profile.voice_id
        )
        self._skills: tuple[LoadedSkill, ...] = ()
        self._generation_task: asyncio.Task[None] | None = None
        self._interrupted = False
        self._status: VoiceStatus | None = None
        self._agent_provider: OpenAIAgentProvider | None = None
        self._tool_executor: ToolExecutor | None = None
        self._pydantic_agent: Any | None = None
        self._tools: tuple[ChatCompletionToolParam, ...] = ()
        self._extra_tools: tuple[ChatCompletionToolParam, ...] = ()
        self._event_messages: deque[ChatMessage] = deque(maxlen=32)
        self._event_message_limit = 2_048
        self._generation_depth = 0
        self._followup_pending = False

    @property
    def role(self) -> VoiceRole:
        return self.profile.role

    @property
    def settings(self) -> VoiceSettings:
        return self._settings

    @property
    def loaded_skills(self) -> tuple[LoadedSkill, ...]:
        return self._skills

    @property
    def agent_provider(self) -> OpenAIAgentProvider | None:
        return self._agent_provider

    @property
    def tools(self) -> tuple[ChatCompletionToolParam, ...]:
        return self._tools

    @property
    def message_history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._event_messages)

    def setup_agent(
        self,
        *,
        agent_provider: OpenAIAgentProvider,
        tool_executor: ToolExecutor,
        extra_tools: tuple[ChatCompletionToolParam, ...] = (),
    ) -> None:
        from kateto.voices.tools import BUILTIN_TOOLS
        self._agent_provider = agent_provider
        self._tool_executor = tool_executor
        self._extra_tools = extra_tools
        self._tools = (*BUILTIN_TOOLS, *extra_tools)

    def add_extra_tools(self, tools: tuple[ChatCompletionToolParam, ...]) -> None:
        self._extra_tools = (*self._extra_tools, *tools)
        self._tools = (*self._tools, *tools)

    def set_pydantic_agent(self, agent: Any) -> None:
        self._pydantic_agent = agent

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
        manager.register_event("voice_request", VoiceRequestData)
        manager.register_event("generate", GenerateData)
        manager.register_event("generate_request", GenerateRequestData)
        manager.register_event("speak", SpeakRequestData)
        manager.register_event("workflow_run", WorkflowRunData)
        manager.register_event("workflow_started", WorkflowStartedData)
        manager.register_event("workflow_phase_start", WorkflowPhaseStartData)
        manager.register_event("workflow_phase_complete", WorkflowPhaseCompleteData)
        manager.register_event("workflow_checkpoint_fail", WorkflowCheckpointFailData)
        manager.register_event("workflow_completed", WorkflowCompletedData)
        manager.register_event("workflow_stop", WorkflowStopData)
        manager.register_event("workflow_stopped", WorkflowStopData)
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
        _remove_pipeline(self.name)
        await self._set_status(VoiceStatus.IDLE)

    async def _enqueue(
        self, envelope: EventEnvelope[BaseModel], handler: EventHandler
    ) -> None:
        self._remember_event(envelope)
        match envelope.name, envelope.data:
            case "interrupt", InterruptData() as interrupt:
                await self.on_interrupt(interrupt)
            case "voice_request", VoiceRequestData() as request:
                await self.on_voice_request(request)
            case "transcription", TranscriptionData():
                await self._set_status(VoiceStatus.WAITING)
                await super()._enqueue(envelope, handler)
            case _:
                await super()._enqueue(envelope, handler)

    async def on_transcription(self, data: TranscriptionData) -> None:
        return None

    async def on_voice_request(self, data: VoiceRequestData) -> None:
        manager = self.manager
        if manager is not None:
            envelope = await manager.emit(
                "generate",
                GenerateData(prompt=data.prompt, workflow=data.workflow, phase_id=data.phase_id),
                source="voice_request",
                target=self.name,
            )
            self._remember_event(envelope)

    async def on_text_chunk(self, data: TextChunk) -> None:
        return None

    async def on_tool_call(self, data: ToolCallData) -> None:
        return None

    async def on_tool_result(self, data: ToolResultData) -> None:
        return None

    async def on_workflow_run(self, data: WorkflowRunData) -> None:
        return None

    async def on_workflow_started(self, data: WorkflowStartedData) -> None:
        return None

    async def on_workflow_phase_start(self, data: WorkflowPhaseStartData) -> None:
        return None

    async def on_workflow_phase_complete(self, data: WorkflowPhaseCompleteData) -> None:
        return None

    async def on_workflow_checkpoint_fail(self, data: WorkflowCheckpointFailData) -> None:
        return None

    async def on_workflow_completed(self, data: WorkflowCompletedData) -> None:
        return None

    async def on_workflow_stop(self, data: WorkflowStopData) -> None:
        return None

    async def on_workflow_stopped(self, data: WorkflowStopData) -> None:
        return None

    async def on_interrupt(self, data: InterruptData) -> None:
        task = self._generation_task
        if task is not None and not task.done():
            self._interrupted = True
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pipeline = get_pipeline(self.name)
        if pipeline is not None:
            pipeline.token_queue = asyncio.Queue(maxsize=64)
            pipeline.pcm_queue = asyncio.Queue(maxsize=32)
        await self._set_status(VoiceStatus.IDLE)

    async def on_generate(self, data: GenerateData) -> None:
        from kateto.plugins.system.turn_gate import Decision

        prompt = self._prompt_for(data)
        # ponytail: is_relevant removed — classification plugin handles intent filtering now
        if prompt is None or not prompt.strip():
            return
        origin = "followup" if self._followup_pending else "external"
        decision = await self._pass_turn_gate(prompt, data, origin=origin, event="generate")
        if decision is not Decision.EXECUTE:
            if decision is Decision.DISCARD:
                self._followup_pending = False
            return
        self._followup_pending = False
        self._interrupted = False
        await self._set_status(VoiceStatus.THINKING)
        generation = asyncio.create_task(
            self._stream_response(
                prompt,
                workflow=data.workflow,
                phase_id=data.phase_id,
            ),
            name=f"kateto-voice-{self.name}",
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

    async def on_generate_request(self, data: GenerateRequestData) -> None:
        from kateto.plugins.system.turn_gate import Decision

        manager = self.manager
        if manager is None:
            return
        if data.depth >= GENERATE_REQUEST_MAX_DEPTH:
            log.warning(
                "[{}] generate_request dropped: depth cap {} reached",
                self.name,
                GENERATE_REQUEST_MAX_DEPTH,
            )
            return
        decision = await self._pass_turn_gate(
            data.prompt, data, origin="followup", event="generate_request"
        )
        if decision is not Decision.EXECUTE:
            return
        self._generation_depth = data.depth + 1
        self._followup_pending = True
        try:
            await manager.emit(
                "generate",
                GenerateData(prompt=data.prompt),
                source=data.source_voice,
                target=data.target_voice,
                dept=data.dept,
            )
        except ValueError as error:
            log.warning("[{}] generate_request rejected: {}", self.name, error)
            gate = self._turn_gate()
            if gate is not None:
                gate.release(self.name)

    async def on_speak(self, data: SpeakRequestData) -> None:
        from kateto.plugins.system.turn_gate import Decision

        prompt = data.prompt
        if prompt is None or not prompt.strip():
            return
        if await self._pass_turn_gate(prompt, data, origin="external", event="speak") is not Decision.EXECUTE:
            return
        self._interrupted = False
        await self._set_status(VoiceStatus.THINKING)
        generation = asyncio.create_task(
            self._stream_response(
                prompt,
                workflow=data.workflow,
                phase_id=data.phase_id,
            ),
            name=f"kateto-voice-{self.name}",
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

    async def _pass_turn_gate(self, prompt: str, data: EventModel, *, origin: str, event: str) -> Decision:
        from kateto.plugins.system.turn_gate import Decision, TurnGate

        gate = self._turn_gate()
        if gate is None:
            return Decision.EXECUTE
        decision = gate.decide(voice=self.name, prompt=prompt, origin=origin)
        if decision is Decision.QUEUE:
            gate.enqueue(event=event, data=data, target=self.name, front=origin == "external")
            log.info("[{}] turn queued ({})", self.name, origin)
        elif decision is Decision.DISCARD:
            log.info("[{}] turn discarded ({})", self.name, origin)
        return decision

    def _turn_gate(self) -> TurnGate | None:
        from kateto.plugins.system.turn_gate import TurnGate

        manager = self.manager
        if manager is None:
            return None
        gate = manager.get_plugin("turn_gate")
        return gate if isinstance(gate, TurnGate) else None

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

    def _get_or_create_pipeline(self) -> AudioPipeline:
        pipeline = _PIPELINES.get(self.name)
        if pipeline is None:
            pipeline = AudioPipeline()
            _PIPELINES[self.name] = pipeline
        return pipeline

    async def _stream_response(
        self,
        prompt: str,
        *,
        workflow: str | None,
        phase_id: str | None,
    ) -> None:
        pipeline = self._get_or_create_pipeline()
        if self._agent_provider is not None and self._tool_executor is not None:
            await self._agent_loop(prompt, workflow=workflow, phase_id=phase_id)
            return
        request = GenerationRequest(
            voice_id=self.name,
            reference_wav=self.reference_wav,
            messages=await self._messages_for(
                prompt,
                workflow=workflow,
                phase_id=phase_id,
            ),
        )
        log.debug("[{}] _settings.stream={}", self.name, self._settings.stream)
        if self._settings.stream:
            log.debug("[{}] stream=true mode, pushing to pipeline", self.name)
            sequence = 0
            async for token in self._provider.stream(request):
                if not isinstance(token, str) or not token:
                    raise ProviderStreamError(
                        voice=self.name, reason="token must be a non-empty string"
                    )
                if self._status is not VoiceStatus.TALKING:
                    await self._set_status(VoiceStatus.TALKING)
                await pipeline.token_queue.put(token)
                await self._emit_chunk(token, sequence, final=False)
                sequence += 1
            await pipeline.token_queue.put(None)
            await self._emit_chunk("", sequence, final=True)
        else:
            log.debug("[{}] stream=false mode, accumulating tokens...", self.name)
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
                log.debug("[{}] stream=false accumulated {} tokens -> {!r}", self.name, len(tokens), full)
                await pipeline.token_queue.put(full)
                await pipeline.token_queue.put(None)
                await self._emit_chunk(full, 0, final=True)
            else:
                await pipeline.token_queue.put(None)
        manager = self.manager
        if manager is not None:
            await manager.emit(
                "voice_idle", VoiceIdleData(voice=self.name), source=self.name
            )
        await self._set_status(VoiceStatus.IDLE)
        _remove_pipeline(self.name)
        self._generation_depth = 0

    async def _agent_loop(
        self,
        prompt: str,
        *,
        workflow: str | None,
        phase_id: str | None,
    ) -> None:
        if self._pydantic_agent is not None:
            await self._pydantic_agent_loop(prompt, workflow=workflow, phase_id=phase_id)
            return
        provider = self._agent_provider
        executor = self._tool_executor
        if provider is None or executor is None:
            return
        pipeline = self._get_or_create_pipeline()
        chat_messages = await self._messages_for(
            prompt,
            workflow=workflow,
            phase_id=phase_id,
        )
        messages: list[dict[str, object]] = [
            {"role": m.role, "content": m.content} for m in chat_messages
        ]
        max_iterations = 10
        try:
            for _ in range(max_iterations):
                if self._interrupted:
                    break
                if self._settings.stream:
                    sequence = 0
                    previous: str | None = None
                    had_tool_calls = False
                    async for item in provider.chat_with_tools_stream(
                        messages=messages,
                        tools=self._tools,
                    ):
                        if self._interrupted:
                            break
                        match item:
                            case StreamToken(text=token) if token:
                                if self._status is not VoiceStatus.TALKING:
                                    await self._set_status(VoiceStatus.TALKING)
                                if previous is not None:
                                    await pipeline.token_queue.put(previous)
                                    await self._emit_chunk(previous, sequence, final=False)
                                    sequence += 1
                                previous = token
                            case AgentResponse() as response if response.tool_calls:
                                if previous is not None:
                                    await pipeline.token_queue.put(previous)
                                    await self._emit_chunk(previous, sequence, final=True)
                                    previous = None
                                await self._handle_tool_calls(
                                    messages=messages, response=response, executor=executor,
                                )
                                had_tool_calls = True
                            case AgentResponse() as response if response.text.strip():
                                await pipeline.token_queue.put(response.text)
                                await self._emit_chunk(response.text, sequence, final=True)
                                previous = None
                                had_tool_calls = False
                                break
                            case _:
                                pass
                    if self._interrupted:
                        break
                    if previous is not None:
                        await pipeline.token_queue.put(previous)
                        await self._emit_chunk(previous, sequence, final=True)
                    if not had_tool_calls:
                        break
                else:
                    response = await provider.chat_with_tools(
                        messages=messages,
                        tools=self._tools,
                    )
                    if not response.tool_calls:
                        if response.text and response.text.strip():
                            await pipeline.token_queue.put(response.text)
                            await self._emit_chunk(response.text, 0, final=True)
                        break
                    await self._handle_tool_calls(
                        messages=messages, response=response, executor=executor,
                    )
        finally:
            await pipeline.token_queue.put(None)
            manager = self.manager
            if manager is not None:
                await manager.emit(
                    "voice_idle", VoiceIdleData(voice=self.name), source=self.name
                )
            await self._set_status(VoiceStatus.IDLE)
            _remove_pipeline(self.name)
            self._generation_depth = 0

    async def _pydantic_agent_loop(
        self,
        prompt: str,
        *,
        workflow: str | None,
        phase_id: str | None,
    ) -> None:
        agent = self._pydantic_agent
        if agent is None:
            return
        pipeline = self._get_or_create_pipeline()
        messages = await self._messages_for(prompt, workflow=workflow, phase_id=phase_id)
        history = _to_pydantic_messages(messages[:-1])
        user_prompt = messages[-1].content if messages else prompt
        try:
            if self._settings.stream:
                sequence = 0
                async with agent.run_stream(user_prompt, message_history=history or None) as result:
                    async for msg in result.stream_text(delta=True):
                        if self._interrupted:
                            break
                        if isinstance(msg, str) and msg:
                            if self._status is not VoiceStatus.TALKING:
                                await self._set_status(VoiceStatus.TALKING)
                            await pipeline.token_queue.put(msg)
                            await self._emit_chunk(msg, sequence, final=False)
                            sequence += 1
                    await pipeline.token_queue.put(None)
                    raw_output = result.get_output()
                    if inspect.isawaitable(raw_output):
                        final_text = await raw_output
                    else:
                        final_text = raw_output
                    if final_text and isinstance(final_text, str):
                        await self._emit_chunk(final_text, sequence, final=True)
            else:
                result = await agent.run(user_prompt, message_history=history or None)
                output = result.output
                if output and isinstance(output, str):
                    await pipeline.token_queue.put(output)
                    await self._emit_chunk(output, 0, final=True)
                await pipeline.token_queue.put(None)
        except asyncio.CancelledError:
            await pipeline.token_queue.put(None)
            raise
        finally:
            manager = self.manager
            if manager is not None:
                await manager.emit("voice_idle", VoiceIdleData(voice=self.name), source=self.name)
            await self._set_status(VoiceStatus.IDLE)
            _remove_pipeline(self.name)
            self._generation_depth = 0

    async def _handle_tool_calls(
        self,
        messages: list[dict[str, object]],
        response: AgentResponse,
        executor: ToolExecutor,
    ) -> None:
        messages.append(
            {
                "role": "assistant",
                "content": response.text or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in response.tool_calls
                ],
            }
        )
        for tc in response.tool_calls:
            correlation_id = uuid4().hex
            manager = self.manager
            if tc.name == "request_generation":
                tc = ToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments={**tc.arguments, "depth": self._generation_depth},
                )
            if manager is not None:
                envelope = await manager.emit(
                    "tool_call",
                    ToolCallData(
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        correlation_id=correlation_id,
                        voice=self.name,
                    ),
                    source=self.name,
                )
                self._remember_event(envelope)
            try:
                result = await executor.execute(tc.name, tc.arguments)
                error = None
            except Exception as e:
                result = ""
                error = str(e)
            if manager is not None:
                envelope = await manager.emit(
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
                self._remember_event(envelope)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result if error is None else f"Error: {error}",
                }
            )

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

    async def _messages_for(
        self,
        prompt: str,
        *,
        workflow: str | None,
        phase_id: str | None,
    ) -> tuple[ChatMessage, ...]:
        soul = await self._memory.read_soul()
        if not soul.strip():
            restored = await self._memory.rollback_soul()
            if restored:
                soul = restored
        memories = await self._memory.read_memories()
        journal = await self._memory.read_journal()
        parts = [self.profile.system_prompt]
        if self._response_language:
            parts.append(
                "Always respond in the project's configured language: "
                f"{self._response_language}. This instruction overrides the language of the user input."
            )
        if workflow is not None and phase_id is not None:
            parts.append(
                "WORKFLOW ENGINE SYSTEM MESSAGE: You are currently executing "
                f"workflow '{workflow}', phase '{phase_id}'. Treat this as an internal "
                "system instruction. Ask the user the questions required by the phase "
                "and use the available tools to complete its task and deliverables. "
                "Do not switch to another workflow because of the user's answer; "
                "continue this workflow until it is completed or you explicitly stop it."
            )
            try:
                definition = WorkflowCatalog(config_dir=self._config_dir).load(
                    workflow=workflow,
                    voice=self.name,
                )
            except WorkflowNotFoundError:
                definition = None
            if definition is not None:
                phase = next(
                    (item for item in definition.phases if item.id.casefold() == phase_id.casefold()),
                    None,
                )
                if phase is not None:
                    tasks = "\n".join(f"- {item}" for item in phase.instructions)
                    deliverables = ", ".join(phase.deliverables) or "none listed"
                    checkpoints = "\n".join(f"- {item}" for item in phase.checkpoints) or "- none listed"
                    parts.append(
                        "Current workflow phase contract:\n"
                        f"Tasks:\n{tasks}\n"
                        f"Deliverables to create or update: {deliverables}\n"
                        f"Checkpoints to verify:\n{checkpoints}\n"
                        "After completing the tasks, dispatch the workflow_phase_complete "
                        "event with the exact workflow, phase_id, voice, deliverables, and "
                        "checkpoint_results. Mark every passed checkpoint with passed=true. "
                        "Do not finish with prose alone."
                    )
        if soul:
            parts.append(soul)
        if memories:
            parts.append(memories)
        if journal:
            parts.append(journal)
        from kateto.voices.prompt_blocks import (
            get_agent_prompt_block,
            get_delegation_prompt_block,
            get_mcp_prompt_block,
            get_workflow_prompt_block,
        )

        workflows = WorkflowCatalog(config_dir=self._config_dir).discover(voice=self.name)
        parts.append(get_workflow_prompt_block(workflows if workflows else None))

        if self._tool_executor is not None:
            mcp_servers = getattr(self._tool_executor, "_mcp_server_names", ())
            if mcp_servers:
                parts.append(get_mcp_prompt_block(mcp_servers))

        if self._pydantic_agent is not None:
            parts.append(get_delegation_prompt_block())

        for skill in self._skills:
            parts.append(skill.instructions)

        # Boson prompt block injection (F11)
        if getattr(self._settings, "tts_provider", "") == "boson" and (set(self.profile.depts) & {"fun"}):
            block = get_agent_prompt_block("boson")
            if block:
                parts.append(block)

        # Semantic memory injection (F7)
        if self.manager is not None:
            memory_plugin = self.manager._plugins.get("memory_sink")
            if memory_plugin is not None and hasattr(memory_plugin, "query_memory"):
                try:
                    relevant = memory_plugin.query_memory(
                        prompt,
                        top_k=3,
                        dept=self.profile.depts[0] if self.profile.depts else None,
                    )
                    if relevant:
                        parts.append("Relevant memories:\n" + "\n".join(f"- {r}" for r in relevant))
                except Exception:
                    pass

        messages = [ChatMessage(role="system", content="\n\n".join(parts))]
        history = tuple(
            message
            for message in self._event_messages
            if not (message.role == "user" and message.content == prompt)
        )
        messages.extend(history)
        messages.append(ChatMessage(role="user", content=prompt))
        return tuple(messages)

    def _remember_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        message: ChatMessage | None = None
        match envelope.data:
            case TranscriptionData(text=text):
                message = ChatMessage(role="user", content=self._bounded_event_text(text))
            case TextChunk(text=text) if text:
                message = ChatMessage(role="assistant", content=self._bounded_event_text(text))
            case VoiceRequestData(prompt=prompt):
                message = ChatMessage(role="user", content=self._bounded_event_text(prompt))
            case GenerateData(prompt=prompt) if prompt is not None:
                message = ChatMessage(role="user", content=self._bounded_event_text(prompt))
            case ToolCallData(tool_name=name, arguments=arguments):
                details = json.dumps(arguments, separators=(",", ":"), sort_keys=True)
                message = ChatMessage(
                    role="assistant",
                    content=self._bounded_event_text(f"tool_call {name}: {details}"),
                )
            case ToolResultData(tool_name=name, result=result, error=error):
                outcome = result if error is None else f"Error: {error}"
                message = ChatMessage(
                    role="assistant",
                    content=self._bounded_event_text(f"tool_result {name}: {outcome}"),
                )
            case WorkflowRunData(workflow=workflow, voice=voice):
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_run {workflow} for {voice}"),
                )
            case WorkflowStartedData(workflow=workflow, voice=voice):
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_started {workflow} for {voice}"),
                )
            case WorkflowPhaseStartData(workflow=workflow, phase_id=phase_id, instructions=instructions):
                details = "; ".join(instructions)
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_phase_start {workflow}/{phase_id}: {details}"),
                )
            case WorkflowPhaseCompleteData(workflow=workflow, phase_id=phase_id, deliverables=deliverables):
                details = "; ".join(deliverables)
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_phase_complete {workflow}/{phase_id}: {details}"),
                )
            case WorkflowCheckpointFailData(workflow=workflow, phase_id=phase_id, checkpoint=checkpoint):
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(
                        f"workflow_checkpoint_fail {workflow}/{phase_id}: {checkpoint}"
                    ),
                )
            case WorkflowCompletedData(workflow=workflow, voice=voice):
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_completed {workflow} for {voice}"),
                )
            case WorkflowStopData(workflow=workflow, voice=voice, reason=reason):
                message = ChatMessage(
                    role="user",
                    content=self._bounded_event_text(f"workflow_stop {workflow} for {voice}: {reason}"),
                )
            case _:
                return
        if not self._event_messages or self._event_messages[-1] != message:
            self._event_messages.append(message)

    def _bounded_event_text(self, text: str) -> str:
        return text[: self._event_message_limit]

    async def _emit_chunk(self, text: str, sequence: int, *, final: bool) -> None:
        manager = self.manager
        if manager is not None:
            envelope = await manager.emit(
                "text_chunk",
                TextChunk(
                    text=text, sequence=sequence, final=final, voice_id=self.name
                ),
                source=self.name,
            )
            self._remember_event(envelope)
