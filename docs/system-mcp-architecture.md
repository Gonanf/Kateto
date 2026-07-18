# System MCP Server - Architecture Note

> 2026-07-18

## The "system" MCP server is NOT a server

The `[mcp_servers.system]` config entry is misleading. `McpEventServer` is **not** an MCP server exposed over stdio or any transport. It is an **in-process tool registry** that wraps the `PluginManager` event bus.

### How it works

1. `run_mode.py:303-313` — `_authorized_mcp_servers()` creates one `McpEventServer` per voice per `"system"` entry
2. `mcp_server.py:117-118` — Creates a `FastMCP` instance and registers tools on it
3. **No `FastMCP.run()` call, no stdio transport, no network binding**
4. Tools are dispatched via Python method calls: `_send_event_tool` → `_dispatch` → `PluginManager.emit()`

### What it actually is

A per-voice in-process object that:
- Registers event-backed tools (e.g., `backlog_add`, `workflow_run`) as MCP-compatible tool definitions
- Holds a `VoiceMemory` for the voice's context
- Provides `refresh_tools()` to sync with current event registrations
- Is stored in `RuntimeComponents.mcp_servers` and started/stopped with the runtime

### Why it exists

The `FastMCP` class from the `mcp` library is used as a **convenient tool schema container**, not as a server. It provides structured tool registration, schema generation, and a clean API — but the transport layer is never used.

### External MCP vs System MCP

| Aspect | External MCP (`ExternalMcpClient`) | System MCP (`McpEventServer`) |
|--------|-----------------------------------|-------------------------------|
| Process | Spawned subprocess via stdio | In-process Python object |
| Transport | stdio (stdin/stdout) | None (direct method calls) |
| Server? | Yes (subprocess is an MCP server) | No (tool registry only) |
| Config | `[mcp_servers.filesystem]` etc. | `[mcp_servers.system]` |
| Filtering | Skipped for `"system"` in `ExternalMcpManager` | Only `"system"` in `_authorized_mcp_servers` |

### Implication

External tools (like mempalace-mcp) are real MCP servers connected via stdio. The "system" server is just authorization metadata — it tells the runtime which voice gets which event-backed tools.
