# 🐱 Kateto — MVP SPEC (Build Week)

**Target:** OpenAI Build Week — Work and Productivity
**Developer:** Solo (using Codex for all development)
**Stack:** Python 3.12+ (async/await), uv, pytest, Pydantic, Textual, OpenAI Python SDK
**Architecture:** Decentralized broker-based event bus. No central mediator.

---

## 1. Goal

Deliver a functional vertical slice of a multi-agent voice assistant. The MVP must demonstrate a **complete conversation loop** with real work capabilities:

audio in → transcription → intent classification → agent generation → TTS audio out

plus live TUI visualization and voice interruption.

### Design Principles

These principles guide every decision:

- **Streaming First** — audio, LLM tokens, and TTS all stream. Latency matters more than anything else. Pipelines are as short as possible, every hop is async, and streaming is the default path (non-streaming only for edge cases).
- **External Inference First** — AI models (Whisper, mmBERT, Zonos, LLM) run as local HTTP servers. Bring Your Own: the user chooses the model, inference platform, and server. The Python process never loads models directly.
- **Conversational** — the system must respond as fast as a human conversation. This means local processing over remote, streaming over batching, and minimum overhead per event hop.
- **Usable** — the system must do real work faster than doing it manually. Not a tech demo: it integrates with real tools (Calendar, terminal, backlog) and produces concrete artifacts.

---

## 2. Core Architecture

### PluginManager (Event Bus)

The **PluginManager** is a singleton that acts as the event bus. It handles plugin lifecycle AND event routing — there is no separate mediator component. Every plugin receives a reference to the manager during initialization.

### Event System

- **Registration:** When a plugin is enabled, the manager scans all its methods starting with `on_*` and registers them as event listeners. Plugins that emit events must register them with name + contract beforehand.
- **Typed Contracts:** Every event has a Pydantic model or dataclass as its contract. Data travels under that contract for type safety.
- **Event Envelope:** Each event carries `source` (plugin name, optionally with `/subsource`), `timestamp` (set automatically by the manager at emit time), `target` (optional specific plugin), and `capabilities` (optional filter list).
- **Fire-and-Forget:** `emit()` dispatches concurrent tasks to all matching subscribers and returns immediately. No guaranteed delivery order.
- **Self-Delivery OFF by default:** An event never reaches the plugin that emitted it (prevents infinite loops). Plugins can opt in if needed.

### Dispatch Filters

Events can be routed three ways, mutually exclusive:

| Mode | Behavior |
|---|---|
| **Broadcast** | No target or capabilities set — event reaches every subscriber that has a matching `on_*` handler. |
| **Target** | `target="voice_jane"` — event goes only to that specific plugin by name. Used for directed voice-to-voice communication. |
| **Capabilities (AND)** | `capabilities=["voice", "agent"]` — event reaches plugins that have ALL listed capabilities. A plugin missing any one does not receive it. |
| **Only Once** | `only_once=True` — the first available subscriber with matching capabilities handles it; no broadcast. Useful for research requests where only one agent should respond. |

### Plugin Queue Types

Each plugin has its own `asyncio.Queue`. Processing mode depends on the plugin type:

- **Streaming plugins** (TTS, Audio Processors): process events one-by-one as they arrive, immediately. No accumulation.
- **Batch plugins** (Voice Agents): accumulate events in their queue and only process when a specific trigger event arrives (`generate`). The trigger is defined by the plugin or its config.

### Error Recovery

If a plugin crashes while processing an event, the error is logged and an **error event** is emitted with the failure context. This allows the TUI, MCP, or other plugins to react — the bus itself stays up.

### Hot-Reload

`watchdog` (inotify on Linux) monitors three locations for file changes (create, modify, delete):

| Watched Path | What Triggers | Effect |
|---|---|---|
| `kateto/plugins/`, `kateto/voices/` | Python file changes (`.py`) | Plugin module is reloaded |
| `config/kateto/voices/{name}/` | SOUL.md, voice config changes | Voice agent is re-prompted with new SOUL on next `generate` |
| `config/kateto/workflows/` | Workflow definition changes | Workflow engine picks up new phases/instructions on next run |

On any change:

1. The plugin's active `asyncio.Task` is gracefully cancelled.
2. Its event queue is cleared.
3. The plugin module (Python) or configuration (SOUL/workflow) is reloaded.

### Config Directory

All configuration and mutable data lives in the platform-standard config directory:

| Platform | Path |
|---|---|
| Linux | `$XDG_CONFIG_HOME/kateto/` (defaults to `~/.config/kateto/`) |
| Windows | `%APPDATA%/kateto/` |

Throughout this document, `config/kateto/` is used as shorthand for the resolved platform path. The Python code determines the path at startup via `os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")` on Linux and `os.environ["APPDATA"]` on Windows.

### Config File

A single `config.toml` file inside the config directory. Each section header matches a plugin name, and the manager injects only the relevant section into each plugin. Secrets (API keys, OAuth tokens) go in `.env` inside the same directory, never in `config.toml`.

---

## 3. MVP Scope

| Component | Description |
|---|---|
| **Audio Input** | `audio_input_mic` (microphone) + `audio_input_meet` (Google Meet capture). Silero VAD detects voice activity. Records until `silence_timeout` seconds of silence, emits `audio_chunk` (`AudioData` — PCM s16LE, 16kHz mono), then immediately resumes listening (async emission means < 50ms gap). On voice activity during playback, emits `interrupt`. Diarization is postponed (P2). |
| **Audio Processor** | `audio_processor_whisper`. Uses `whisper-large-v3-turbo` via local HTTP server (whisper.cpp). Receives `audio_chunk`, emits `transcription` (`TranscriptionData`). Single-processor pipeline — no chaining in MVP. |
| **Audio Output** | `audio_output_zonos` (TTS engine with speaker embeddings for voice consistency) + `audio_output_player` (playback). TTS streams sentence-by-sentence PCM chunks to the player. **Reference voice clips are required per agent** — each voice (Jane, Doktor, Conquest) needs a short sample clip so Zonos can synthesize consistent timbre. |
| **Classifier** | mmBERT fine-tuned to GGUF, served via llama.cpp HTTP. Three-way intent classification: `EXECUTE` (directed at the system), `IGNORE_SELF_TALK` (user talking to themselves), `IGNORE_THIRD_PARTY` (conversation not meant for the system). On `EXECUTE`, emits `generate` to ALL active P0 voices. Per-voice routing (VoiceClassifier) is P1 — in MVP all three voices receive the prompt and self-filter by relevance. |
| **Interrupt Executor** | Listens for the `interrupt` event from audio input. Calls `on_interrupt()` on all Voice agents and the TTS plugin. Cancels active OpenAI SDK HTTP streams safely via `asyncio.Task.cancel()`. After cancellation, the audio input resumes listening — the conversation loop restarts from the top. |
| **TODO List Executor** | Detects when work items need tracking. Creates `config/kateto/voices/{voice}/TODO.md` with structured tasks. Integrates with the backlog system — when a task is completed, the backlog is updated via MCP. |
| **Voices** | Three agents: **Jane** (orchestrator, default voice, hard Polish-accented woman), **Doktor** (Product Owner — formal, empathetic, manages backlog/calendar/risk), **Conquest** (SCRUM Master — passionate, strict, enforces process). All inherit from `VoiceAgent(Plugin)`. |
| **TUI** | Textual-based terminal UI. Polls the manager via `get_plugins()` and `get_events()` to display active/inactive plugins and live event stream. Supports enabling/disabling plugins at runtime and sending events manually. Used for demo visualization and debugging. |
| **MCP Server** | Serves a Model Context Protocol API that exposes the PluginManager interface as tools. **Auto-discovery:** the server scans registered event receivers and data types to dynamically generate tool schemas. Key tool: `send_event(event_name, data, target, wait=False)` — when `wait=True`, the call blocks until the targeted plugin emits a response event (enables request-response patterns over the async bus). |
| **Backlog** | `product_backlog.json` managed via MCP tools: `backlog_list` (filter by status/priority), `backlog_add` (create item), `backlog_update` (modify status/priority). Basic CRUD for work items, accessible by both agents (via MCP tool calls) and humans (via Codex or TUI). Doktor (PO) owns the backlog; Conquest reads it for sprint tracking. |
| **Connectors** | **Google Calendar** (OAuth2 installed-app flow, token cached in `config/kateto/secrets/` — reads/writes events via getter/setter pattern), **Google Meet** (audio capture via `audio_input_meet`), **CLI** (restricted to an allow-list in `config.toml` — no arbitrary shell execution). Connectors use a `reply_to` field in their event contracts: when a voice requests data (e.g., "what meetings today?"), the connector processes it and emits the response back to the requesting voice's queue using the `reply_to` target. |

---

## 4. Voices Implementation

### Voice Creation — Two Modes

A voice can be created in two ways:

#### Manual (Python Subclass)

A Python file in `kateto/voices/` that inherits from `VoiceAgent`. Required when the voice needs custom logic, specialized event handlers, or unique workflow orchestration.

```
kateto/voices/
├── base.py                  # VoiceAgent base class
├── jane.py                  # manual — orchestrator, interrupt handling
├── doktor.py                # manual — backlog, calendar, risk
└── conquest.py              # manual — sprint ceremonies, process
```

Used by P0 voices (Jane, Doktor, Conquest) that have distinct behaviors beyond a system prompt.

#### Declarative (Auto-Generated from Folder)

A directory in `config/kateto/voices/{name}/` with a `SOUL.md`. No Python file needed — the PluginManager auto-creates a generic `VoiceAgent` instance using the SOUL.md as its system prompt. The voice data directory path is injected into the instance at startup.

```
config/kateto/voices/
├── Narrador/
│   ├── SOUL.md              # System prompt = the voice's entire personality
│   ├── JOURNAL.md
│   └── MEMORIES.md
└── Susurrante/
    └── SOUL.md
```

This is how all P1+ voices work (Narrador, Susurrante, all P2 voices). They are personality variations on the same `VoiceAgent` base — no custom executors, connectors, or processing logic. They can have custom workflows assigned per-voice.

#### Auto-Detection Flow

The PluginManager handles both modes transparently:

1. Scans `kateto/voices/` for Python files defining `VoiceAgent` subclasses → **manual** voices
2. Scans `config/kateto/voices/` for subdirectories containing `SOUL.md` → **declarative** voices
3. Each discovered voice is instantiated, injected with its config section and data directory path, and registered as a plugin
4. If a data directory is missing for a manual voice, it is created with defaults
5. Hot-reload applies to both modes — change a `.py` file or a `SOUL.md`, watchdog picks it up

### Base Class

`VoiceAgent` inherits from `Plugin`. It uses the OpenAI Python SDK for HTTP LLM calls, which is compatible with both the OpenAI API and local llama.cpp servers (which expose an OpenAI-compatible API).

### Processing Mode

Voices are **batch** plugins: they accumulate events in their queue and only generate a response when they receive a `generate` event (dispatched by the Classifier). When triggered, the voice processes its accumulated context and calls the LLM. Generation is a streaming async generator — tokens are yielded one by one.

### Memory & Context Files

Each voice has three files in `config/kateto/voices/{name}/`:

| File | Purpose | Size Limit | Mutation |
|---|---|---|---|
| `SOUL.md` | System prompt — personality, role, behavior rules | 500 words max | Rewritten by the agent after 5 minutes of system idle. The agent reads its current SOUL + JOURNAL + MEMORIES and rewrites it, preserving core identity while incorporating new experiences. |
| `JOURNAL.md` | Stream of consciousness — thoughts, decisions, observations | Sliding window: 50 entries or 3000 tokens (whichever hits first) | Append-only. The agent writes entries during or after tasks. Oldest entries are dropped when the window fills. |
| `MEMORIES.md` | Long-term recall — facts, preferences, important context | 1000 words max | Agent-managed. The agent decides what to add and what to prune when the limit is reached. |

### Idle Detection

When the LLM returns an end-of-text token, the voice emits a `voice_idle` event. This signal is used by:

- **Workflow engine:** to auto-advance to the next workflow phase.
- **TODO Executor:** to check if there's pending work and prompt the voice to continue.
- **TUI:** to display voice state (speaking / idle / thinking).

### TTS Voice Consistency

Zonos uses speaker embeddings for consistent voice timbre. Each voice agent requires a **reference audio clip** (a few seconds of speech in the target voice style) that is loaded at startup. The TTS plugin selects the appropriate embedding based on the `source` field of the incoming text event.

### Skills

Skills are **reusable abilities** that voices can invoke — they are recipes, not code. A skill lives in a directory with markdown instructions that the voice reads and follows, optionally with templates and scripts.

```
config/kateto/skills/{skill_name}/
├── SKILL.md              # What this skill does and how to use it
├── templates/            # Output templates
└── scripts/              # Optional deterministic scripts
```

Unlike MCP servers (external processes) or plugins (event bus participants), skills are **knowledge** — markdown that the LLM ingests as context. A voice uses a skill when a task requires it: "use the backlog skill to create a new task" means the voice reads `skills/backlog/SKILL.md` and follows its instructions.

**Available skills are defined per voice** in `config.toml`:

```toml
[voice.doktor]
skills = ["backlog", "risk-analysis", "planning-poker"]
```

When a voice has skills enabled, the contents of `SKILL.md` for each enabled skill are injected into the system prompt at session start. This gives the LLM structured knowledge of how to perform specialized tasks without hardcoding logic.

Available skills (MVP):

- `backlog` — managing tasks and sprints
- `calendar` — reading/creating calendar events
- `risk-analysis` — evaluating project risks

---

## 5. Workflows (MVP Limitation)

Workflows are **instructions given to a voice** to execute a process step by step. They are not autonomous code — they are directives the voice receives as prompts and must fulfill, phase by phase.

### Workflow Locations

Workflows live in two places, both monitored by hot-reload:

| Location | Purpose | Example |
|---|---|---|
| `config/kateto/workflows/{name}/` | **Global workflows** shared across voices (e.g., daily standup, sprint review) | `config/kateto/workflows/daily-standup/workflow.py` |
| `config/kateto/voices/{voice}/workflows/{name}/` | **Per-voice workflows** specific to an agent's role (e.g., Doktor's sprint-planning workflow) | `config/kateto/voices/Doktor/workflows/sprint-planning/workflow.py` |

Global workflows can be assigned to any voice at runtime. Per-voice workflows are available only to that agent.

### v1 Behavior

- Workflows are strictly **declarative** (no imperative `run` scripts). The voice receives phase instructions as natural language and uses its LLM to interpret and execute them.
- The voice maintains an internal TODO list tracking each phase: `in_progress`, `done`, `cancelled`.
- Each phase defines **checkpoints** — conditions that must be verified before advancing. If a checkpoint fails, the workflow pauses and the voice must resolve the issue (emit `workflow_checkpoint_fail`).
- **Auto-advance:** when the voice is idle (emitted `voice_idle`) and the current phase is `done`, the system automatically advances to the next phase. If the current phase is `in_progress`, the system prompts the voice to finish it.
- **Stopped state:** the voice can stop a workflow at any time via `workflow_stop`. The workflow is marked `stopped` and no further events are sent for it.

### Workflow Lifecycle Events

All workflow state changes are emitted as events so the rest of the system (TUI, other voices, MCP) stays informed:

| Event | When | Payload |
|---|---|---|
| `workflow_started` | Workflow begins | workflow, voice, context |
| `workflow_phase_start` | A phase activates | workflow, phase_id, voice |
| `workflow_phase_complete` | A phase finishes | workflow, phase_id, deliverables |
| `workflow_checkpoint_fail` | A checkpoint doesn't pass | workflow, phase_id, checkpoint, voice |
| `workflow_completed` | Last phase done, all checkpoints passed | workflow, voice |
| `workflow_stopped` | Workflow aborted by voice or system | workflow, voice, reason |

---

## 6. Data Concurrency & Safety

### CLI Connector

Commands are restricted to an **allow-list** defined in `config.toml`. The connector checks every command against the list before execution. No arbitrary shell access — this is a hard security boundary.

### File Locking

`product_backlog.json` uses `asyncio.Lock` per file combined with atomic writes (write to temp file, then `os.rename()`). The lock is released immediately after the write completes. This prevents corruption from concurrent agent access while keeping the blocking window minimal.

### Voice File Isolation

Voices cannot write to each other's `SOUL.md`, `JOURNAL.md`, or `MEMORIES.md` files. Each voice's context directory is private to that agent. Cross-voice communication happens exclusively through events on the bus.

---

## 7. Directory Structure

```
kateto/                          # Project code (versioned)
├── core/
│   ├── plugin.py                # Plugin base class
│   ├── manager.py               # PluginManager + event bus
│   ├── event.py                 # Event system
│   ├── config.py                # TOML config loader + first-run bootstrap
│   └── hot_reload.py            # Watchdog watcher
├── plugins/
│   ├── audio_input/
│   │   ├── base.py
│   │   └── mic.py
│   ├── audio_processor/
│   │   └── whisper.py
│   ├── audio_output/
│   │   ├── zonos.py
│   │   └── player.py
│   ├── executor/
│   │   ├── classifier.py
│   │   ├── interrupt.py
│   │   └── todo_list.py
│   ├── connector/
│   │   ├── calendar.py
│   │   ├── google_meet.py
│   │   └── cli.py
│   └── system/
│       ├── tui.py
│       └── mcp_server.py
├── voices/
│   ├── base.py                  # VoiceAgent base class
│   ├── jane.py                  # Manual voice — Python subclass
│   ├── doktor.py                # Manual voice — Python subclass
│   └── conquest.py              # Manual voice — Python subclass
├── config/
│   └── defaults/                # Versioned defaults — copied to ~/.config/kateto/ on first run
│       ├── config.toml
│       ├── voices/
│       │   ├── Doktor/
│       │   │   └── workflows/
│       │   │       ├── sprint-planning/workflow.py
│       │   │       └── sprint-review/workflow.py
│       │   └── Conquest/
│       │       └── workflows/
│       │           ├── daily-standup/workflow.py
│       │           └── sprint-retrospective/workflow.py
│       ├── workflows/
│       │   └── daily-standup/   # Global workflows
│       └── skills/
│           ├── backlog/
│           └── calendar/
└── tests/

~/.config/kateto/                # Linux ($XDG_CONFIG_HOME/kateto/)
                                # Windows (%APPDATA%/kateto/)
                                # Copied from config/defaults/ on first run, then mutable
├── config.toml                  # Main configuration
├── voices/                      # Per-voice data (SOUL, memories, workflows)
│   ├── Jane/
│   │   ├── SOUL.md
│   │   ├── JOURNAL.md
│   │   ├── MEMORIES.md
│   │   └── workflows/
│   ├── Doktor/
│   │   └── workflows/
│   │       ├── sprint-planning/
│   │       │   └── workflow.py
│   │       └── sprint-review/
│   │           └── workflow.py
│   └── Conquest/
│       └── workflows/
│           ├── daily-standup/
│           │   └── workflow.py
│           └── sprint-retrospective/
│               └── workflow.py
├── workflows/                   # Global workflows (shared across voices)
│   └── daily-standup/
├── skills/                      # Markdown-defined abilities (SKILL.md + templates)
│   ├── backlog/
│   │   ├── SKILL.md
│   │   └── templates/
│   └── calendar/
│       └── SKILL.md
└── secrets/                     # .env, OAuth tokens (gitignored)
    └── .env

On first run, `config.py` checks if `~/.config/kateto/` exists. If not, it copies the entire `config/defaults/` tree there. After that, the config directory is mutable — users can edit files, and hot-reload picks up changes. The `config/defaults/` tree in the repo is the reference for upgrades (user can diff to see what changed).
```

## 8. Repo & Logistics

- **License:** MIT. **Visibility:** Public.
- **Tooling:** Strictly `uv` (no pip/poetry, no conda). `pytest` + `pytest-asyncio` for testing. TDD (RED → GREEN → REFACTOR) is the development process — no hard coverage gate, but the cycle is mandatory.
- **Testing:** Mocking external HTTP servers is NOT required. If local servers (whisper.cpp, llama.cpp, Zonos) are running, tests can use them directly. This keeps tests realistic without mocking complexity.
- **MCP Servers:** Defined globally in `config.toml` under `[mcp_servers]`. The MCP Plugin discovers them and exposes their tools. Auto-discovery refers to scanning available **event types** in the system, not scanning system processes.

---

## 9. Codex Directives (LazyCodex)

These rules must be followed by Codex during all development:

- Write code modularly inside the `kateto/` directory structure as specified.
- Always use `async/await` — no synchronous blocking calls.
- Isolate logic into plugins. Never use central mediators — communication is always through the event bus.
- Ensure all event data structures inherit from Pydantic `BaseModel`.
- Handle file writes securely with `asyncio.Lock` + atomic rename.
- Do **not** implement P1/P2 features: VoiceClassifier, extra voices beyond the three P0, Narrador/Susurrante, Avatars, Workspaces, imperative workflow phases.
