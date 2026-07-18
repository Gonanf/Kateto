# Ponytail Review — Agreed Simplifications

Based on the repo-wide audit, filtered by design decisions in [`design-decisions.md`](design-decisions.md).

## Scope

Changes to make. Each entry is a self-contained unit with a clear "done" state.

---

## 1. Delete Dead Code

### 1.1 `main.py` at repo root

6-line stub, never imported. Entry point is `kateto/__main__:main` via pyproject.

**Done when:** File deleted.

### 1.2 Thin QA wrapper scripts

`scripts/qa/voice_fixture.py` (6 lines) and `scripts/qa/vertical_slice.py` (10 lines) just re-import the real module.

**Done when:** Both files deleted. Callers invoke `kateto.qa.voice_fixture` / `kateto.qa.vertical_slice` directly.

---

## 2. Delete Stale Future-P3 Docs

`docs/.temp` — 269-line SVG screenshot of TUI, stale artifact.  
`docs/concepts/avatars.md` — P3 feature, never built.  
`docs/concepts/workspaces.md` — P3 feature, never built.  
`docs/development/masks-prompts.md` — 295 lines of SVG generation prompts for never-built avatars.  

**Done when:** Those files deleted. Future docs live in an `archive/` dir or only created when the feature is scoped.

---

## 3. Collapse Single-Impl Protocols

28 Protocol classes across the codebase, each with exactly one concrete implementation. Replace with concrete types.

| File | Protocols to remove | Concrete replacement |
|------|--------------------|---------------------|
| `kateto/plugins/audio_input/base.py` | `SileroModel`, `VoiceActivityDetector`, `PcmBuffer`, `CaptureTimeInfo`, `CaptureStatus`, `CaptureCallback`, `CaptureStream` (keep `CaptureFactory`) | Name the types directly: `SileroVad`, `CallbackQueue`, `SoundDeviceCapture`, etc. |
| `kateto/plugins/audio_input/silero.py` | `SileroModelLoader`, `SileroTensor`, `SileroModelOutput`, `RawSileroModel` | Use concrete types from `torch`, inline the model loader |
| `kateto/plugins/connector/calendar.py` | `InstalledAppCredentials`, `InstalledAppFlow`, `OAuthTokenProvider`, `CalendarTransport` | Use google lib types directly (they satisfy structurally already) |
| `kateto/plugins/audio_output/base.py` | `AudioOutputStream`, `AudioOutputFactory` | Replace with concrete `SoundDeviceOutputStream`, `SoundDeviceOutputFactory` |
| `kateto/plugins/audio_output/zonos.py` | `PcmStreamingProvider` | Replace with `Callable[..., Coroutine[...]]` type alias |
| `kateto/plugins/connector/cli.py` | `CommandRunner` | Delete, use `CliConnector._run_command` directly |
| `kateto/plugins/audio_input/capture.py` | `RawInputStream` | Delete, use `sounddevice.RawInputStream` directly |
| `kateto/providers/agent.py` | `AgentProvider` | Delete (zero impls), keep `ToolExecutor` if used |
| `kateto/voices/base.py` | `StreamingProvider` | Merge into `OpenAICompatibleProvider` |
| `kateto/core/plugin.py` | `PluginManagerProtocol` | Delete, use `PluginManager` directly in type hints |
| `kateto/run_mode.py` | `CalendarConnectorFactory` | Delete (zero impls, only None-checked in prod) |
| `kateto/plugins/system/tui_runtime.py` | `TuiMcpServer`, `TuiRuntime` | Delete (zero impls), keep `TuiConfigurationRuntime` |
| `kateto/plugins/audio_output/player.py` | `RawOutputStream` | Delete, use `sounddevice.RawOutputStream` directly |

**Done when:** All Protocol definitions above removed, their call sites updated to use concrete types directly, imports cleaned.

---

## 4. Consolidate Custom Exceptions

48 custom `@dataclass(slots=True)` exception classes across 22 files, each with 1-2 fields + `__str__`. Replace with a small set of shared types.

Most map to 5 categories:

| Category | Files affected |
|----------|---------------|
| `ConfigError(msg)` | `config.py` (6 classes → 1) |
| `ProviderError(msg)` | `providers/errors.py` (4 → 1) |
| `PluginError(msg)` | `mcp_server.py` (7 → 1), `audio_input/base.py` (3 → 1), `audio_output/base.py` (2 → 1), `silero.py` (1), `cli.py` (2), `hot_reload.py` (1) |
| `StorageError(msg)` | `storage.py` (1), `backlog.py` (4 → 1) |
| `AudioError(msg)` | `audio_input/base.py` (3), `audio_output/base.py` (2) — overlaps with PluginError |

Exceptions that carry distinct structured data (not just a message) keep their own class. Everything else becomes a message-string exception.

**Done when:** ~48 custom exception classes reduced to ≤6. All catch sites updated.

---

## 5. Inline Trivial `@property` → Public Attributes

~40 properties that are `return self._x`. Pattern:

```python
@property
def manager(self) -> PluginManager:
    return self._event_runtime.manager
```

Hotspots:

| File | Count | Fix |
|------|-------|-----|
| `kateto/run_mode.py` | 9 | Expose `_components` / `_event_runtime` directly, or make attrs public |
| `kateto/plugins/system/tui_runtime.py` | 11 | Same — most are on Protocol classes that are being removed anyway |
| `kateto/plugins/audio_input/listener.py` | 3 | `capture_task`, `resumed_listening`, `last_resume_gap_ms` → public attrs |
| `kateto/plugins/audio_input/base.py` | 3 | `pending`, `dropped_frames`, `rejected_frames` on `CallbackQueue` |
| `kateto/plugins/system/mcp_server.py` | 4 | `fastmcp`, `server_name`, `voice_name`, `pending_wait_count` |
| `kateto/voices/base.py` | 4 | `role`, `loaded_skills`, `agent_provider`, `tools` |

**Done when:** All `return self._x` property+private-attr pairs replaced with a single public attribute. `@property` kept only when it computes or validates.

---

## 6. Replace Hand-Coded Voice Classes With Auto-Generated Factory

Three voice subclasses (`jane.py`, `doktor.py`, `conquest.py`) are structurally identical ~20-line files:

```python
class Jane(VoiceAgent):
    def __init__(self, ...) -> None:
        super().__init__(profile=_PROFILE, ...)

def create_voice(ctx, settings):
    provider = _Provider(...)
    voice = Jane(config_dir=..., provider=provider, settings=settings)
    ...
    return voice
```

**Target:** A single factory that reads `VoiceProfile` from config + `SOUL.md` and returns a generic `VoiceAgent` instance. No Python subclass needed for standard voices.

**Direction:** Documented in `design-decisions.md` and `docs/voices/voice-agent.md` ("Declarative P1+"). This is the migration path — the P0 hand-coded classes are temporary.

**Done when:** `kateto/voices/jane.py`, `doktor.py`, `conquest.py` removed (or reduced to one-liner config). A generic factory in `kateto/voices/base.py` or `kateto/voices/factory.py` handles all standard voices.

---

## 7. Delete Triple QA System

Three parallel validation layers: `kateto/tests/`, `kateto/qa/`, `scripts/qa/`. All do similar things with fixture plugins, fake providers, and subprocess runners.

| Layer | Files | Purpose |
|-------|-------|---------|
| `kateto/tests/` | 37 test files | pytest unit + integration tests |
| `kateto/qa/` | 8 fixture modules | Deterministic fake providers for scenario testing |
| `scripts/qa/` | 8 Python scripts | CLI-run QA scenarios using the `kateto.qa` fixtures |

**Keep:** Core tests in `kateto/tests/` (smoke, plugin_manager, conversation_loop).  
**Delete:** `kateto/qa/` (fixture modules), `scripts/qa/` (wrapper scripts).  
**Migrate:** Any QA scenario not covered by kept tests moves into a single integration test per scenario.

**Done when:** `kateto/qa/` and `scripts/qa/` directories removed. Test count reduced from 37 to ≤10.

---

## 8. Delete Empty Scaffolding Directories

| Directory | Notes |
|-----------|-------|
| `skills/calendar/` | Referenced in config, no SKILL.md |
| `skills/backlog/templates/` | No templates written |
| `config/defaults/skills/calendar/` | Empty default |
| `config/defaults/skills/backlog/templates/` | Empty default |
| `config/defaults/workflows/daily-standup/` | Workflow defs live under voices/ |
| `workflows/daily-standup/` | Same |

**Done when:** Directories removed from version control. Config references to `skills/calendar` removed or annotated as optional.

---

## 9. Delete Case-Duplicated Voice Directories

`voices/conquest/` + `voices/Conquest/`, `voices/doktor/` + `voices/Doktor/` — six dirs for three voices. One of each pair is a stray case variant from dev environment file creation.

**Done when:** The canonical directory per voice is confirmed (lowercase or capitalized), the duplicate is removed, and `git rm` cleans the extra.

---

## 10. Fix Config Drift

Root `config.toml` missing 4 plugin sections present in `config/defaults/config.toml`:

- `[plugin.backlog]`
- `[plugin.connector_cli]`
- `[plugin.executor_interrupt]`
- `[plugin.executor_todo_list]`

**Done when:** Root `config.toml` has matching sections, or the defaults are removed if those plugins aren't ready for dev use.

---

## 11. Clean Up `live.py` EventRuntime Wrapper

`kateto/live.py` (67 lines) defines `EventRuntime` which wraps `PluginManager` + a plugin tuple. The class has `start()`/`stop()`/`plugins` property, all delegating to the manager or internal set.

```python
class EventRuntime:
    def __init__(self, *, manager, plugins):
        self.manager = manager
        self._plugins = frozenset(plugins)

    @property
    def plugins(self):
        return tuple(self._plugins)  # just returns the set as tuple
```

**Done when:** `EventRuntime` is removed. Callers use `PluginManager` and plugin tuple directly. The `build_event_runtime()` function becomes a standalone function that returns a `PluginManager`.

---

## 12. Deduplicate `event.py` Enum Validators

Three Pydantic models in `kateto/core/event.py` have identical `@field_validator` methods:

- `BacklogItem` (lines ~207-215)
- `BacklogListData` (lines ~222-230)
- `BacklogUpdateData` (lines ~246-254)

Each does `try: BacklogPriority(value) except: BacklogStatus(value)`.

**Done when:** A single shared `_parse_backlog_enum` validator replaces the three copies.

---

## 13. Merge Duplicate Methods in `voices/tools.py`

`_send_event` (lines 88-110) and `_dispatch_event` (lines 69-86) have nearly identical logic: look up a registration, validate with contract, emit.

**Done when:** Merged into one method with a flag or parameter controlling the minor differences (target vs no target, source attribution).

---

## Sequencing

| Pass | Items | Effort |
|------|-------|--------|
| **1: Immediate** | Delete dead code (#1, #2), empty scaffolding (#8), case-duplicate dirs (#9), config drift (#10) | Minutes |
| **2: Protocol purge** | Collapse 28 Protocols → concrete types (#3) | 1-2 hours |
| **3: Exception consolidation** | 48 → 5 exception classes (#4) | 1 hour |
| **4: Property inline** | ~40 properties → public attrs (#5) | 1 hour |
| **5: Voice factory** | Replace 3 hand-coded voice classes (#6) | 2 hours |
| **6: QA trim** | Delete qa/ + scripts/qa/, keep core tests (#7) | 1 hour |
| **7: Remaining cleanup** | live.py (#11), validators (#12), tools merge (#13) | 30 min |
