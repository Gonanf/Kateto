# Kateto — AGENTS.md

## What It Is

Kateto is an event-driven voice team for project work. Jane orchestrates, Doktor handles planning/backlog, Conquest facilitates agile ceremonies. All communication runs through a PluginManager that is simultaneously the event bus and plugin lifecycle manager — no separate mediator.

**Stack:** Python 3.12+ async/await · uv · pytest-asyncio · Pydantic · Textual 8 · MCP 1.28

---

## Entrypoints & Commands

```
uv run kateto config check              # validate TOML, bootstrap defaults
uv run kateto run                        # event runtime (no TUI)
uv run kateto tui                        # text UI with event stream
uv run kateto tui --fixture              # TUI with deterministic fixtures
uv run kateto smoke --fixture            # full bounded smoke test
```

--fixture mode is the no-network fallback — supplies transcription, classification, streaming, and PCM via mocks. External servers (whisper.cpp, llama.cpp, Zonos) only needed for live runs.

## Architecture

### PluginManager (Event Bus + Lifecycle)

```python
# Singleton. Scans `on_*` methods for subscriber registration.
# Plugin emits → Manager dispatches to matching subscribers concurrently.
```

**Plugin types:**
- `audio_input/` — mic capture (sounddevice), silence detection with Silero VAD
- `audio_processor/` — Whisper transcription
- `audio_output/` — Zonos TTS, PCM playback
- `connector/` — CLI allowlist, Google Calendar/Meet
- `executor/` — Classifier (intent), Interrupt, TODO List, Backlog
- `system/` — TUI (Textual), internal MCP server
- `work/` — (future)

Each plugin gets its own `asyncio.Queue`. Streaming plugins process events one-by-one as they arrive. Batch plugins (voice agents) accumulate and process on `generate` trigger.

### Event System

- Registration: auto-scanned from `on_*` methods on enabled plugins
- Contracts: every event has a Pydantic model (frozen, strict — `EventModel` in `core/event.py`)
- Envelope: `EventEnvelope(name, data, source, timestamp, target, capabilities, only_once)`
- Dispatch filters: Broadcast · Target · Capabilities (AND) · Only Once
- Self-delivery OFF by default (prevents loops)

Errors are caught per-plugin and emitted as error events. The bus stays up.

### Voices (3 built-in: Jane, Doktor, Conquest)

Defined in `kateto/voices/factory.py` with `VoiceProfile` (voice_id, display_name, role, system_prompt). Config keys in `config.toml` are lowercase (`voice.jane`, `voice.doktor`, `voice.conquest`). Directory names in `config/defaults/voices/` match lowercase.

Voice lifecycle:
1. `create_voice()` reads profile, creates `VoiceAgent` with `OpenAICompatibleProvider`
2. `VoiceAgent` sets up `VoiceMemory` (per-voice file store in `~/.config/kateto/voices/{name}/`)
3. Optional: agent provider + `VoiceToolExecutor` for tool-enabled generation

### Config Bootstrap

```
config/defaults/config.toml  +  config/defaults/voices/{name}/workflows/
    → _copy_missing_defaults() → user config dir
```
Bootstrap copies missing files only (does not overwrite existing). User config at `$XDG_CONFIG_HOME/kateto` or `~/.config/kateto/`.

**Precedence:** user config > config/defaults/ > hardcoded (factory.py)

All code resolves voice paths via `config_dir / "voices" / voice_name`. Defaults directory is NOT used at runtime — only for initial bootstrap.

### Hot Reload

`watchdog` monitors `kateto/plugins/`, `kateto/voices/`, and user config voice/workflow dirs. On file change: cancel plugin task → clear queue → reload module/config. Graceful — the bus stays up.

### Workflow System

Declarative Python files in `{voice_dir}/workflows/{name}/workflow.py`. Fields: `name`, `description`, `voice`, `phases` (array with id/instructions/deliverables/checkpoints). Loaded by `WorkflowCatalog` (discovery via `casefold()` comparison — case-insensitive). Executed by `WorkflowEngine`.

---

## Project Structure

```
kateto/
├── kateto/
│   ├── __main__.py      # Entrypoint: main() dispatches argv
│   ├── run_mode.py      # RuntimeOwner, RuntimeComponents assembly
│   ├── live.py          # build_event_runtime() — wires everything
│   ├── core/
│   │   ├── event.py     # EventModel base, all event contracts
│   │   ├── manager.py   # PluginManager (singleton + event bus)
│   │   ├── plugin.py    # Plugin base class
│   │   ├── config.py    # TOML loading, bootstrap, ConfigPaths
│   │   ├── discovery.py # Plugin/plugin discovery by directory
│   │   ├── workflow.py  # WorkflowCatalog, WorkflowDefinition
│   │   ├── workflow_engine.py  # WorkflowEngine (runner)
│   │   ├── hot_reload.py # HotReloadController (watchdog)
│   │   ├── storage.py   # VoiceFileStore (path isolation)
│   │   └── exceptions.py
│   ├── voices/
│   │   ├── factory.py   # create_voice(), VoiceProfile dict
│   │   ├── base.py      # VoiceAgent (profile, memory, generation)
│   │   ├── memory.py    # VoiceMemory
│   │   ├── skills.py    # load_skills()
│   │   └── tools.py     # VoiceToolExecutor (built-in + user tools)
│   ├── plugins/
│   │   ├── audio_input/  # mic capture
│   │   ├── audio_output/ # TTS, PCM playback
│   │   ├── audio_processor/ # whisper
│   │   ├── connector/    # CLI, Calendar, Meet
│   │   ├── executor/     # Classifier, Interrupt, TODO, Backlog
│   │   └── system/       # TUI, MCP server
│   └── tests/            # 41 files, pytest-asyncio
├── docs/
│   ├── known-issues.md   # Bug index (overview table)
│   ├── bugs/             # Individual bug files
│   ├── architecture/     # System design docs
│   ├── plugins/          # Plugin-specific docs
│   ├── voices/           # Voice architecture docs
│   └── development/      # TDD, tooling, build week
├── config/
│   └── defaults/         # Bootstrap template (config.toml, voices, skills)
└── script/
    └── qa/               # Fixture scripts, acceptance.py
```

---

## Testing

### Commands

```bash
# Run everything (excluding collection-error tests)
uv run pytest

# Single test with verbose output
uv run pytest kateto/tests/test_workflow.py::test_workflow_catalog_discover_voice_with_workflows -v

# Run a test file
uv run pytest kateto/tests/test_storage.py -v

# Fastest feedback — run the core+workflow+config tests
uv run pytest kateto/tests/test_event_bus.py kateto/tests/test_plugin_manager.py kateto/tests/test_config.py kateto/tests/test_workflow.py kateto/tests/test_storage.py -v
```

### Patterns

- **pytest-asyncio** (strict mode). Async tests must be marked with `@pytest.mark.asyncio` or they won't be collected.
- **BDD-style comments:** `# Given:`, `# When:`, `# Then:` throughout test files.
- **Fixture helpers:** `kateto/tests/conversation_support.py` — `make_voices()` creates all 3 voices. `_write_workflow()` in test_workflow.py. `_McpRuntime` in test_tui.py.
- **tmp_path** used for config dirs — tests create minimal temp config structures, never touch real user config.

### Known Pre-existing Failures

These are NOT caused by your changes:

| Failure | Why |
|---------|-----|
| `test_tui_uses_bounded_manager_history_and_applies_audio_configuration` | Tab order hardcoded as 5 but runtime has 6 (Conversation tab added between Events and Plugins) |
| `test_tui_workspace_tabs_status_history_and_json_composer` | Same tab mismatch |
| 7 test files with collection error | Missing `kateto.qa` module — external QA scripts, not part of core |
| `test_cli_connector` | Missing QA scripts |
| `test_conversation_support` | Missing module dependency |

### Config-loading note

Tests that need config should use explicit `load_config(config_dir=tmp_path, defaults_dir=tmp_path / "defaults")` — the default `load_config()` resolves to real user config. Use `mktemp -d` or `tmp_path` to avoid contaminating the developer's config.

---

## Bug Reporting Workflow

**Any bug encountered during development MUST be documented.** The format:

### 1. Create bug file

`docs/bugs/NN-description-breve.md` where NN is the next available ID:

```yaml
---
id: 17                    # sequential, next after highest existing
title: "TUI plugins tab: ..."
severity: Media           # Baja | Media | Alta | Crítica
status: open              # open | resolved
component: kateto/tests/test_tui.py   # path or module name
resolved: 2026-07-19      # only if status=resolved (newer convention)
---

## NN. Title (same as frontmatter title)

**Severidad:** Media
**Componente:** `path/to/component`

### Descripción

What the bug is, why it matters.

### Impacto

What breaks or degrades.

### Causa

Root cause analysis.

**Posible solución:** (for open bugs)
1. Step 1
2. Step 2

**Solución aplicada:** (for resolved bugs)
Summary of what was done.

**Archivos:** `file1.py`, `file2.py`
```

### 2. Update the index

Add the bug to `docs/known-issues.md`:
- If open: add to "Abiertos" table
- If resolved: add to "Resueltos (✅)" table
- Tables: `| NN | Title | Severidad | Componente | [file](./bugs/NN-file.md) |`

### 3. Work on it

For open bugs: create a todo item, fix, update status to `resolved`, add date + solution to the bug file, move entry to "Resueltos" in the index.

---

## Codebase Gotchas

### Case Sensitivity

All voice/workflow name comparisons use `casefold()` — case-insensitive by design. But `VoiceFileStore.for_voice()` resolves `config_dir / "voices" / voice` literally. On case-sensitive filesystems, the directory name must match the config key exactly (lowercase: `conquest`, `doktor`, `jane`).

### config/defaults/ Is NOT for Runtime

The `config/defaults/` directory is a bootstrap template. At runtime, ONLY the user config directory (`~/.config/kateto/`) is read. Changes to `config/defaults/` only take effect on first bootstrap of a new config.

### Fixture Mode

`--fixture` flag replaces all external services with deterministic mocks. Useful for:
- Demo without whisper.cpp/llama.cpp/Zonos
- Tests that need reproducible output
- TUI screenshots

### Workflow Files Are Python

Workflow definitions in `{voice}/workflows/{name}/workflow.py` are actual Python files parsed via `ast.parse`. Only simple literal assignments are supported: `name`, `description`, `voice`, `phases`, `auto_advance`, `can_stop`. No imports, no function calls, no variables.

### Voice Tool Executor

`VoiceToolExecutor` in `kateto/voices/tools.py` provides 13 built-in tools including file operations, skill loading, and runtime tools (create_skill, update_skill, create_workflow, update_workflow, update_soul). MCP servers declared in config.toml are injected per-voice.

### TUI Switch for Plugins

Each plugin row in the TUI has `Switch(value=plugin.enabled, id=f"switch-{plugin.name}")`. Toggling it fires `on_switch_changed` → `_set_plugin` → `manager.enable_plugin/disable_plugin`. Do NOT add separate enable/disable buttons — use the Switch.

### Pony Tail Conventions

This project uses ponytail conventions for intentional simplification. Mark deliberate shortcuts with `ponytail:` comments. Examples found in the codebase:
- `# ponytail: no backup in these wrappers, add when tools are stable`
- `# ponytail: global lock, per-account locks if throughput matters`

### .gitignore

`.omo/evidence/` and `.sisyphus/` are gitignored. Evidence dirs and plan files are local-only.

### Deprecated Dirs (deleted)

These root dirs were removed as duplicates — do NOT recreate them:
- `skills/` (root) → use `config/defaults/skills/`
- `scripts/` (empty) → use `script/`
- `voices/` (root) → dev workspace only, not code-referenced
- `workflows/` (root) → empty
- `TODO.md` (root) → stale

