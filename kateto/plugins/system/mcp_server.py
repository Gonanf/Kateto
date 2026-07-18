from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

import anyio
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, JsonValue

from kateto.core.config import KatetoConfig
from kateto.core.event import EventEnvelope, PluginErrorData
from kateto.core.manager import EventRegistration, PluginManager
from kateto.voices.memory import VoiceMemory


DEFAULT_WAIT_TIMEOUT: Final = 5.0


@dataclass(frozen=True, slots=True)
class McpServerNotDeclaredError(Exception):
    server_name: str

    def __str__(self) -> str:
        return f"MCP server is not declared: {self.server_name}"


@dataclass(frozen=True, slots=True)
class McpVoiceUnauthorizedError(Exception):
    voice_name: str
    server_name: str

    def __str__(self) -> str:
        return f"voice {self.voice_name} is not authorized for MCP server {self.server_name}"


@dataclass(frozen=True, slots=True)
class McpEventUnavailableError(Exception):
    event_name: str

    def __str__(self) -> str:
        return f"MCP event is not available from a live receiver: {self.event_name}"


@dataclass(frozen=True, slots=True)
class McpTargetUnavailableError(Exception):
    event_name: str
    target: str

    def __str__(self) -> str:
        return f"MCP target {self.target} cannot receive event {self.event_name}"


@dataclass(frozen=True, slots=True)
class McpWaitTargetRequiredError(Exception):
    event_name: str

    def __str__(self) -> str:
        return f"MCP wait requires a target for event {self.event_name}"


@dataclass(frozen=True, slots=True)
class McpWaitTimeoutError(Exception):
    correlation_id: str
    timeout_seconds: float

    def __str__(self) -> str:
        return f"MCP wait timed out after {self.timeout_seconds}s: {self.correlation_id}"


@dataclass(frozen=True, slots=True)
class McpReplyError(Exception):
    correlation_id: str
    error: PluginErrorData

    def __str__(self) -> str:
        return f"MCP reply failed for {self.correlation_id}: {self.error.message}"


class McpEventResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_name: str
    correlation_id: str
    target: str | None
    response_event: str | None = None
    response_data: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True)
class McpServerOptions:
    server_name: str
    voice_name: str
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT


class _PendingReply:
    def __init__(self, reply_address: str, target: str) -> None:
        self.reply_address = reply_address
        self.target = target
        self.ready = anyio.Event()
        self.response: EventEnvelope[BaseModel] | None = None


class McpEventServer:
    def __init__(
        self,
        manager: PluginManager,
        config: KatetoConfig,
        options: McpServerOptions,
        config_dir: Path | None = None,
    ) -> None:
        self._manager = manager
        self._options = options
        self._authorize(config)
        self.fastmcp = FastMCP(f"kateto-{options.server_name}")
        self.fastmcp.add_tool(self._send_event_tool, name="send_event", structured_output=True)
        self.server_name = options.server_name
        self.voice_name = options.voice_name
        self._voice_memory: VoiceMemory | None = None
        if config_dir is not None:
            self._voice_memory = VoiceMemory.for_voice(config_dir=config_dir, voice=options.voice_name)
        self._reply_address = f"mcp/{options.server_name}/{options.voice_name}"
        self._waiters: dict[str, _PendingReply] = {}
        self._event_tool_names: set[str] = set()
        self._manager.add_event_observer(self._observe_event)
        self._register_memory_tools()
        self.refresh_tools()

    @property
    def pending_wait_count(self) -> int:
        return len(self._waiters)

    async def close(self) -> None:
        self._manager.remove_event_observer(self._observe_event)
        self._waiters.clear()

    def refresh_tools(self) -> None:
        for tool_name in self._event_tool_names:
            self.fastmcp.remove_tool(tool_name)
        self._event_tool_names.clear()
        for registration in self._manager.get_event_registrations():
            if registration.receivers and registration.name != "send_event":
                self._add_event_tool(registration)

    def _register_memory_tools(self) -> None:
        self.fastmcp.add_tool(self._memory_read_tool, name="memory_read")
        self.fastmcp.add_tool(self._memory_append_tool, name="memory_append")
        self.fastmcp.add_tool(self._memory_set_soul_tool, name="memory_set_soul")

    async def _memory_read_tool(
        self, source: str
    ) -> str:
        memory = self._voice_memory
        if memory is None:
            return "error: memory is not configured for this server"
        match source:
            case "soul":
                return await memory.read_soul()
            case "journal":
                return await memory.read_journal()
            case "memories":
                return await memory.read_memories()
            case _:
                return f"invalid memory source: {source!r} (expected soul, journal, or memories)"

    async def _memory_append_tool(
        self, target: str, entry: str
    ) -> str:
        memory = self._voice_memory
        if memory is None:
            return "error: memory is not configured for this server"
        match target:
            case "journal":
                await memory.append_journal(entry)
                return "ok"
            case "memories":
                await memory.append_memories(entry)
                return "ok"
            case _:
                return f"invalid memory target: {target!r} (expected journal or memories)"

    async def _memory_set_soul_tool(self, soul: str) -> str:
        memory = self._voice_memory
        if memory is None:
            return "error: memory is not configured for this server"
        await memory.write_soul(soul)
        return "ok"

    async def send_event(
        self,
        event_name: str,
        data: dict[str, JsonValue],
        target: str | None = None,
        wait: bool = False,
    ) -> McpEventResult:
        registration = self._registration(event_name)
        payload = registration.contract.model_validate(data)
        return await self._dispatch(registration, payload, target, wait)

    async def _send_event_tool(
        self,
        event_name: str,
        data: dict[str, JsonValue],
        target: str | None = None,
        wait: bool = False,
    ) -> McpEventResult:
        return await self.send_event(event_name, data, target, wait)

    async def _dispatch(
        self,
        registration: EventRegistration,
        payload: BaseModel,
        target: str | None,
        wait: bool,
    ) -> McpEventResult:
        if wait and target is None:
            raise McpWaitTargetRequiredError(event_name=registration.name)
        if target is not None and target not in registration.receivers:
            raise McpTargetUnavailableError(event_name=registration.name, target=target)
        correlation_id = uuid4().hex
        waiter = _PendingReply(self._reply_address, target) if wait and target is not None else None
        if waiter is not None:
            self._waiters[correlation_id] = waiter
        try:
            await self._manager.emit(
                registration.name,
                payload,
                source=self._reply_address,
                target=target,
                reply_to=self._reply_address if wait else None,
                correlation_id=correlation_id,
            )
            if waiter is None:
                return McpEventResult(
                    event_name=registration.name,
                    correlation_id=correlation_id,
                    target=target,
                )
            try:
                with anyio.fail_after(self._options.wait_timeout):
                    await waiter.ready.wait()
            except TimeoutError as error:
                raise McpWaitTimeoutError(correlation_id, self._options.wait_timeout) from error
            response = waiter.response
            if response is None:
                raise McpWaitTimeoutError(correlation_id, self._options.wait_timeout)
            if response.name == "error":
                error_data = PluginErrorData.model_validate(response.data.model_dump())
                raise McpReplyError(correlation_id, error_data)
            return McpEventResult(
                event_name=registration.name,
                correlation_id=correlation_id,
                target=target,
                response_event=response.name,
                response_data=response.data.model_dump(mode="json"),
            )
        finally:
            self._waiters.pop(correlation_id, None)

    def _authorize(self, config: KatetoConfig) -> None:
        if self._options.server_name not in config.mcp_servers:
            raise McpServerNotDeclaredError(server_name=self._options.server_name)
        voice = config.voice.get(self._options.voice_name)
        if voice is None or self._options.server_name not in voice.mcp_servers:
            raise McpVoiceUnauthorizedError(
                voice_name=self._options.voice_name,
                server_name=self._options.server_name,
            )

    def _registration(self, event_name: str) -> EventRegistration:
        for registration in self._manager.get_event_registrations():
            if registration.name == event_name and registration.receivers:
                return registration
        raise McpEventUnavailableError(event_name=event_name)

    def _add_event_tool(self, registration: EventRegistration) -> None:
        async def event_tool(
            data: BaseModel,
            target: str | None = None,
            wait: bool = False,
        ) -> McpEventResult:
            return await self._dispatch(registration, data, target, wait)

        event_tool.__name__ = f"event_{registration.name}"
        event_tool.__annotations__["data"] = registration.contract
        event_tool.__annotations__["return"] = McpEventResult
        self.fastmcp.add_tool(event_tool, name=registration.name, structured_output=True)
        self._event_tool_names.add(registration.name)

    def _observe_event(self, envelope: EventEnvelope[BaseModel]) -> None:
        correlation_id = envelope.correlation_id
        if correlation_id is None:
            return
        waiter = self._waiters.get(correlation_id)
        if waiter is None:
            return
        if envelope.target != waiter.reply_address:
            return
        if envelope.source.split("/", maxsplit=1)[0] != waiter.target:
            return
        waiter.response = envelope
        waiter.ready.set()
