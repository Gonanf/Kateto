# Hot-Reload

The system detects changes to plugin code, voice data, and workflow definitions and reacts automatically without requiring a restart. Uses `watchdog` (inotify on Linux).

## Watched Locations

| Path | What Triggers | Effect |
|---|---|---|
| `kateto/plugins/`, `kateto/voices/` | Python file changes (`.py`) | Plugin module is reloaded |
| `config/kateto/voices/{name}/` | `SOUL.md`, voice config changes | Voice agent is re-prompted with new SOUL on next `generate` |
| `config/kateto/workflows/` | Workflow definition changes | Workflow engine picks up new phases/instructions |

## Reload Sequence

When a change is detected:

1. The plugin's active `asyncio.Task` is **gracefully cancelled** — in-progress HTTP streams are cancelled, current generation is aborted
2. The plugin's **event queue is cleared** — pending events for the old version are discarded
3. The module or configuration is **reloaded** — new code takes effect immediately

## What Changes Are Supported

- **Create**: New plugin files are detected and loaded automatically
- **Modify**: Changed files trigger reload of the affected plugin
- **Delete**: Removed plugins are unregistered and their queue cleaned up

## Graceful Cancellation

Active tasks (LLM HTTP streams, TTS playback) are cancelled via `asyncio.Task.cancel()`. The system ensures:

- The OpenAI SDK HTTP stream is properly closed
- The TTS playback stops cleanly
- The audio input resumes listening
- No partial state is left behind
