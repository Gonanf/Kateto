"""External MCP clients per voice — processes spawned via stdio.

One file, two classes, nothing abstract, no factories for one product.
Uses the already-installed ``mcp[1.28.1]`` library: ``stdio_client``,
``ClientSession``, ``StdioServerParameters``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai.types.chat import ChatCompletionToolParam

from kateto.core.config import McpServerSettings

log = logging.getLogger(__name__)


class ExternalMcpClient:
    """Client for a single external MCP server process (stdio)."""

    def __init__(self, name: str, command: str, args: list[str]) -> None:
        self.name = name
        self._command = command
        self._args = args
        self._session: ClientSession | None = None
        self._session_cm: Any = None
        self._transport_cm: Any = None
        self._tools: list | None = None  # cached tool list

    async def start(self) -> None:
        """Spawn the subprocess, connect stdio, initialise session."""
        params = StdioServerParameters(command=self._command, args=self._args)
        try:
            self._transport_cm = stdio_client(params)
            read, write = await self._transport_cm.__aenter__()
            self._session_cm = ClientSession(read, write)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
        except Exception as exc:
            log.warning("External MCP '%s' failed to start: %s", self.name, exc)
            await self.stop()

    async def list_tools(self) -> list:
        """Return the raw MCP tool list (cached after first fetch)."""
        if self._session is None:
            return []
        if self._tools is None:
            result = await self._session.list_tools()
            self._tools = result.tools
        return self._tools

    async def list_chat_tools(self) -> tuple[ChatCompletionToolParam, ...]:
        """Convert MCP tools to OpenAI chat-completion tool format."""
        tools = await self.list_tools()
        chat: list[ChatCompletionToolParam] = []
        for t in tools:
            chat.append(
                ChatCompletionToolParam(
                    type="function",
                    function={
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema
                        or {"type": "object", "properties": {}},
                    },
                )
            )
        return tuple(chat)

    async def has_tool(self, name: str) -> bool:
        """Check whether this server exposes a tool with *name*."""
        tools = await self.list_tools()
        return any(t.name == name for t in tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool with a 30 s timeout. Returns text-only result."""
        if self._session is None:
            return '{"error": "MCP client not started"}'
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments), timeout=30.0
            )
            texts: list[str] = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            return "\n".join(texts)
        except asyncio.TimeoutError:
            return f'{{"error": "MCP tool timed out: {name}"}}'

    async def stop(self) -> None:
        """Close session + subprocess cleanly."""
        try:
            if self._session_cm is not None:
                await self._session_cm.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            if self._transport_cm is not None:
                await self._transport_cm.__aexit__(None, None, None)
        except Exception:
            pass
        self._session = None
        self._session_cm = None
        self._transport_cm = None
        self._tools = None

    @property
    def is_running(self) -> bool:
        return self._session is not None


class ExternalMcpManager:
    """Manages one ``ExternalMcpClient`` per declared server name.

    Clients are shared across voices — if two voices both declare
    ``filesystem`` only one subprocess is spawned.
    """

    def __init__(self) -> None:
        self._clients: dict[str, ExternalMcpClient] = {}
        self._voice_servers: dict[str, list[str]] = {}

    def configure(
        self, voice_name: str, server_name: str, settings: McpServerSettings
    ) -> None:
        """Register an external server for *voice_name* (idempotent)."""
        if server_name not in self._clients:
            self._clients[server_name] = ExternalMcpClient(
                server_name, settings.command, settings.args
            )
        self._voice_servers.setdefault(voice_name, []).append(server_name)

    async def start_all(self) -> None:
        """Start every registered client. Failed servers log a warning."""
        results = await asyncio.gather(
            *(c.start() for c in self._clients.values()), return_exceptions=True
        )
        for (name, _client), result in zip(self._clients.items(), results):
            if isinstance(result, BaseException):
                log.warning("External MCP '%s' failed to start: %s", name, result)

    async def get_tools_for(
        self, server_names: list[str]
    ) -> tuple[ChatCompletionToolParam, ...]:
        """Return chat-formatted tools for every running external server in the list."""
        all_tools: list[ChatCompletionToolParam] = []
        for name in server_names:
            if name == "system":
                continue
            client = self._clients.get(name)
            if client is not None and client.is_running:
                all_tools.extend(await client.list_chat_tools())
        return tuple(all_tools)

    async def try_call_tool(
        self,
        server_names: list[str],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str | None:
        """Try to call *tool_name* on any external server. ``None`` = not found."""
        for name in server_names:
            if name == "system":
                continue
            client = self._clients.get(name)
            if client is not None and client.is_running and await client.has_tool(tool_name):
                return await client.call_tool(tool_name, arguments)
        return None

    def get_servers_for_voice(self, voice_name: str) -> list[str]:
        return self._voice_servers.get(voice_name, [])

    async def stop_all(self) -> None:
        """Stop every running client."""
        results = await asyncio.gather(
            *(c.stop() for c in self._clients.values()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                log.warning("Error stopping external MCP: %s", result)
        self._clients.clear()
        self._voice_servers.clear()
