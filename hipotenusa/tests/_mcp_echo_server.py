"""Minimal MCP echo server for testing — stdio transport, single tool."""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


async def main() -> None:
    server = Server("echo")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="Echo back the message",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Message to echo"},
                    },
                    "required": ["message"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "echo":
            return [TextContent(type="text", text=json.dumps({"echoed": arguments.get("message", "")}))]
        raise ValueError(f"Unknown tool: {name}")

    async with stdio_server() as (read, write):
        init = server.create_initialization_options()
        await server.run(read, write, init, raise_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
