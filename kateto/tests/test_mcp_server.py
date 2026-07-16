from __future__ import annotations

import pytest

from kateto.core import Plugin, PluginManager
from kateto.core.config import KatetoConfig
from kateto.core.event import BacklogListData, EventModel
from kateto.plugins.system.mcp_server import McpEventResult, McpEventServer, McpServerOptions


class SchemaReceiver(Plugin):
    def __init__(self) -> None:
        super().__init__("backlog")

    async def on_backlog_list(self, data: BacklogListData) -> None:
        return None


class FailingReceiver(Plugin):
    def __init__(self) -> None:
        super().__init__("broken")

    async def on_backlog_list(self, data: BacklogListData) -> None:
        msg = "fixture failure"
        raise RuntimeError(msg)


class BacklogReply(EventModel):
    items: list[str]


class ReplyingReceiver(Plugin):
    def __init__(self) -> None:
        super().__init__("backlog")

    async def on_backlog_list(self, data: BacklogListData) -> None:
        request = self.current_envelope
        if request is None:
            msg = "request envelope is required for a reply"
            raise RuntimeError(msg)
        if self.manager is None:
            msg = "manager is required for a reply"
            raise RuntimeError(msg)
        await self.manager.emit(
            "backlog_list_reply",
            BacklogReply(items=["first"]),
            source=self.name,
            target=request.reply_to,
            correlation_id=request.correlation_id,
        )


@pytest.mark.asyncio
async def test_registered_receiver_contracts_are_available_to_mcp_schema_builder() -> None:
    # Given: a receiver with a registered Pydantic event contract.
    manager = PluginManager()
    manager.register_event("backlog_list", BacklogListData)
    await manager.enable_plugin(SchemaReceiver())

    try:
        # When: an MCP schema builder queries the manager's registrations.
        registrations = manager.get_event_registrations()

        # Then: it receives the event name, BaseModel contract, and live receiver name.
        registration = next(item for item in registrations if item.name == "backlog_list")
        assert registration.contract is BacklogListData
        assert registration.receivers == ("backlog",)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_correlated_request_failure_emits_a_reply_addressed_error() -> None:
    # Given: a targeted receiver that raises while serving an MCP request.
    manager = PluginManager()
    manager.register_event("backlog_list", BacklogListData)
    await manager.enable_plugin(FailingReceiver())

    try:
        # When: a request supplies its reply address and correlation identifier.
        await manager.emit(
            "backlog_list",
            BacklogListData(),
            source="mcp/fixture/doktor",
            target="broken",
            reply_to="mcp/fixture/doktor",
            correlation_id="request-1",
        )
        await manager.wait_for_idle()

        # Then: the propagated error is routable to exactly the waiting caller.
        error = manager.get_events()[-1]
        assert error.name == "error"
        assert error.target == "mcp/fixture/doktor"
        assert error.correlation_id == "request-1"
    finally:
        await manager.close()


def test_voice_mcp_access_requires_an_explicit_declared_server_grant() -> None:
    # Given: a configured global MCP server and one voice explicitly granted access.
    config = KatetoConfig.model_validate(
        {
            "kateto": {},
            "cli": {"allowlist": ["ls"]},
            "mcp_servers": {"fixture": {"command": "not-a-real-process"}},
            "voice": {"doktor": {"mcp_servers": ["fixture"]}},
        },
    )

    # When: the typed configuration crosses the TOML boundary.
    configured_servers = config.voice["doktor"].mcp_servers

    # Then: the grant remains explicit rather than implicitly inheriting all servers.
    assert configured_servers == ["fixture"]


@pytest.mark.asyncio
async def test_fastmcp_generates_a_registered_receiver_schema_and_returns_a_correlated_reply() -> None:
    # Given: an authorized voice, a live receiver, and its registered request/reply contracts.
    config = KatetoConfig.model_validate(
        {
            "kateto": {},
            "cli": {"allowlist": ["ls"]},
            "mcp_servers": {"fixture": {"command": "not-a-real-process"}},
            "voice": {"doktor": {"mcp_servers": ["fixture"]}},
        },
    )
    manager = PluginManager()
    manager.register_event("backlog_list", BacklogListData)
    manager.register_event("backlog_list_reply", BacklogReply)
    await manager.enable_plugin(ReplyingReceiver())
    server = McpEventServer(manager, config, McpServerOptions("fixture", "doktor", 0.2))

    try:
        # When: an MCP client lists and calls the generated event tool with wait enabled.
        tools = {tool.name: tool for tool in await server.fastmcp.list_tools()}
        _, raw_result = await server.fastmcp.call_tool(
            "backlog_list",
            {"data": {}, "target": "backlog", "wait": True},
        )
        result = McpEventResult.model_validate(raw_result)

        # Then: the tool uses the registered Pydantic schema and returns the matching reply.
        assert tools["backlog_list"].inputSchema["properties"]["data"]["$ref"] == "#/$defs/BacklogListData"
        assert result.response_event == "backlog_list_reply"
        assert result.response_data == {"items": ["first"]}
    finally:
        await server.close()
        await manager.close()
