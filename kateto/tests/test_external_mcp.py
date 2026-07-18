"""Integration tests for external MCP clients using a real echo server."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from kateto.core.config import McpServerSettings
from kateto.plugins.system.external_mcp import ExternalMcpClient, ExternalMcpManager

ECHO_SERVER = str(Path(__file__).parent / "_mcp_echo_server.py")


@pytest.fixture
def echo_settings() -> McpServerSettings:
    return McpServerSettings(command=sys.executable, args=[ECHO_SERVER])


@pytest.mark.asyncio
async def test_external_mcp_client_start_and_list_tools(echo_settings: McpServerSettings) -> None:
    client = ExternalMcpClient("echo", echo_settings.command, echo_settings.args)
    await client.start()
    try:
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "echo"
        chat_tools = await client.list_chat_tools()
        assert chat_tools[0]["function"]["name"] == "echo"
        assert client.is_running
    finally:
        await client.stop()
    assert not client.is_running


@pytest.mark.asyncio
async def test_external_mcp_client_call_tool(echo_settings: McpServerSettings) -> None:
    client = ExternalMcpClient("echo", echo_settings.command, echo_settings.args)
    await client.start()
    try:
        result = await client.call_tool("echo", {"message": "hello"})
        assert "hello" in result
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_external_mcp_client_has_tool(echo_settings: McpServerSettings) -> None:
    client = ExternalMcpClient("echo", echo_settings.command, echo_settings.args)
    await client.start()
    try:
        assert await client.has_tool("echo")
        assert not await client.has_tool("nonexistent")
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_external_mcp_manager_configure_start_and_tools(echo_settings: McpServerSettings) -> None:
    manager = ExternalMcpManager()
    manager.configure("jane", "echo", echo_settings)
    await manager.start_all()
    try:
        tools = await manager.get_tools_for(["echo"])
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "echo"
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_external_mcp_manager_try_call_tool(echo_settings: McpServerSettings) -> None:
    manager = ExternalMcpManager()
    manager.configure("doktor", "echo", echo_settings)
    await manager.start_all()
    try:
        result = await manager.try_call_tool(["echo"], "echo", {"message": "test"})
        assert result is not None
        assert "test" in result
        missing = await manager.try_call_tool(["echo"], "nope", {})
        assert missing is None
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_external_mcp_manager_shared_servers(echo_settings: McpServerSettings) -> None:
    manager = ExternalMcpManager()
    manager.configure("jane", "echo", echo_settings)
    manager.configure("doktor", "echo", echo_settings)
    await manager.start_all()
    try:
        assert manager.get_servers_for_voice("jane") == ["echo"]
        assert manager.get_servers_for_voice("doktor") == ["echo"]
        assert len(manager._clients) == 1
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_external_mcp_client_handles_bad_command() -> None:
    client = ExternalMcpClient("bad", "nonexistent_binary_xyz", [])
    await client.start()
    try:
        tools = await client.list_tools()
        assert tools == []
    finally:
        await client.stop()
