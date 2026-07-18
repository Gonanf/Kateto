# Jane Capability Test — Evidence Report

> 2026-07-18 · Test script: `_test_jane_full.py`

## Test Configuration

- **Model:** Kateto (unsloth/LFM2.5-8B-A1B-GGUF, reasoning model)
- **Endpoint:** http://127.0.0.1:11434/v1 (ollama/llama.cpp)
- **Voices enabled:** jane
- **MCP servers:** system (in-process only)
- **Audio input:** enabled (PulseAudio, silero VAD)

## Results Summary

| # | Test | Status | Detail |
|---|------|--------|--------|
| 1 | System MCP architecture | PASS | In-process only, 20 tools, no stdio |
| 2 | Jane builtin tools | PASS | 8 tools: run_command, read_file, write_file, send_event, list_events, enable/disable/list_plugins |
| 3 | Jane event tools | PASS | 11 tools: interrupt, classification, todo_completed, audio_chunk, transcription, backlog_list/add/update |
| 4 | Jane generate (basic) | FAIL | Timeout 60s — audio capture blocks event loop |
| 5 | backlog_list | PASS | Event dispatched without error |
| 6 | backlog_add | PASS | Event dispatched with BacklogItem(id="test-001", title="Item de prueba") |
| 7 | backlog_list (after add) | PASS | Event dispatched |
| 8 | classification -> TODO create | PASS | ClassificationData(text="recordar comprar leche", EXECUTE) dispatched |
| 9 | classification -> TODO complete | PASS | ClassificationData(text="done comprar leche", EXECUTE) dispatched |
| 10 | List plugins via generate | FAIL | Model responded but text_chunk capture lost content |
| 11 | Enable doktor via generate | FAIL | Timeout 60s — same audio capture issue |
| 12 | Enable conquest via generate | FAIL | Timeout 60s — same audio capture issue |
| 13 | generate receivers | PASS | ['jane'] |
| 14 | Enabled plugins (11) | PASS | executor_todo_list, executor_interrupt, executor_classifier, backlog, audio_output_player, connector_cli, audio_processor_whisper, audio_output_zonos, audio_input_mic, jane, workflow_engine |
| 15 | WorkflowEngine | PASS | Found but no workflows defined on disk |

## Bugs Found

### Bug #1: Audio capture blocks event loop (CRITICAL)
- **Test:** #4, #11, #12
- **Impact:** All generate calls timeout when audio_input_mic is enabled
- **Root cause:** `kateto-audio-capture-audio_input_mic` task runs blocking audio loop in asyncio event loop
- **Ticket:** docs/known-issues.md #8

### Bug #2: Text chunk capture loses content (LOW)
- **Test:** #10
- **Impact:** Model responses partially lost in capture
- **Root cause:** LLM reasoning model generates empty first text chunk
- **Ticket:** docs/known-issues.md #9

### Bug #3: doktor/conquest not separate plugins (DESIGN)
- **Test:** #11, #12
- **Impact:** Cannot enable/disable doktor/conquest via enable_plugin tool
- **Root cause:** doktor/conquest are voice configurations in factory.py, not Plugin instances. The enable_plugin tool only works with Plugin objects registered in PluginManager.
- **Note:** This is a design limitation, not a bug. Voices are configured in config.toml, not dynamically enabled.

## Architecture Findings

### System MCP is NOT a server
The `[mcp_servers.system]` config entry creates `McpEventServer` objects that are **in-process tool registries**, not stdio servers. They use `FastMCP` as a schema container but never call `FastMCP.run()`. External clients cannot connect to them.

**Evidence:**
```
system MCP 'system' voice='jane': In-process only (tools=20, stdio=False)
```

### Voice capabilities are event-driven
All tool calls from the LLM go through `VoiceToolExecutor.execute()` which:
1. Matches built-in tools (run_command, read_file, etc.)
2. Falls back to external MCP (if configured)
3. Falls back to event dispatch (if tool name matches a registered event)

### Backlog is file-based
Backlog operations read/write `product_backlog.json` with file-locking. Events are synchronous within the manager.

### TODO is classifier-driven
TODO items are created/completed via `classification` events with EXECUTE category. The text must match patterns: `plan|todo|task|remember <task>` or `complete|done|finish <task>`.

## Commands Run

```bash
# Start runtime and run tests
timeout 300 uv run python _test_jane_full.py

# Direct LLM test (works without audio plugins)
uv run python -c "
import asyncio
from kateto.core.config import load_config
from kateto.run_mode import build_runtime_owner
async def main():
    config = load_config()
    owner = build_runtime_owner(config)
    await owner.start()
    for p in owner.manager.get_plugins():
        if p.name == 'jane':
            msgs = await p._messages_for('hola')
            chat_msgs = [{'role': m.role, 'content': m.content} for m in msgs]
            resp = await p._agent_provider.chat_with_tools(messages=chat_msgs, tools=p._tools)
            print(f'Response: {resp.text}')
    await owner.stop()
asyncio.run(main())
"
```
