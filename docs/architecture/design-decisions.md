# Design Decisions

## Hot-Reload Is a First-Class Feature

The hot-reload module (`kateto/core/hot_reload.py`) is deliberately built and kept, even though it's disabled by default (`hot_reload = false` in shipped configs).

**Rationale:** The system is a development platform for voice agents. During active development — iterating on SOUL prompts, workflow definitions, and plugin code — the restart cycle is the bottleneck. Hot reload eliminates it. Enabled at the developer's choice via config.

**Architecture:** See [`docs/architecture/hot-reload.md`](hot-reload.md) for the reload sequence and supported change types.

## Dependencies Are Intentional

All runtime dependencies are deliberate choices, not convenience bloat:

| Dependency | Why, not what stdlib replacement |
|---|---|
| `httpx` | Async HTTP throughout. `urllib` is sync-only without thread-pool hacks. Every provider (Whisper, LLM, TTS, classifier) streams async. |
| `numpy` | Audio buffer manipulation in capture pipeline. `array('h')` works for trivial cases but numpy handles resampling, normalization, and the reshape/view patterns the audio pipeline needs. |
| `python-dotenv` | Explicit .env loading with `.env` precedence rules, quoting, and comment handling. Stdlib inline parsing drifts on edge cases. |
| `watchdog` | Native inotify on Linux (hot-reload). `os.stat` polling misses renames, temp-file writes, and adds latency. Hot reload depends on correctness, not approximation. |
| `pydantic` | Boundary validation for every external input (config files, MCP requests, SSE streams, plugin events). Pydantic `ValidationError` provides structured error context. `dataclasses` throw bare `TypeError` with no trace of which field failed. |
| `torch` | Silero VAD requires PyTorch runtime. Direct pin acknowledges this even though `silero-vad` pulls it transitively — makes the dependency explicit. |
| `mcp` | Model Context Protocol server implements the MCP spec. No stdlib equivalent. |
| `sounddevice` | Cross-platform audio capture/playback via PortAudio. No stdlib API for audio device access. |
| `textual` | Terminal UI framework. No stdlib equivalent for async TUI. |
| `openai` | OpenAI-compatible LLM API (works with llama.cpp, OpenAI, and compatible servers). No stdlib equivalent. |
| `google-auth-oauthlib` | Google Calendar OAuth2 flow. Conditional import via `importlib`, not loaded unless calendar connector is configured. |

**Guiding principle:** Zero new dependencies unless they pull their weight. The existing set is reviewed and approved. No dep is removed without a concrete (not theoretical) stdlib alternative that covers the same edge cases.

## Declarative Voice Generation

Voice agents should be auto-generated from configuration + data files, not hand-written as Python Plugin subclasses.

**Current state (to be migrated away from):**
- `kateto/voices/jane.py`, `doktor.py`, `conquest.py` — hand-coded classes inheriting from `VoiceAgent`
- Each is ~20 lines that only configures a `VoiceProfile` and calls `super().__init__()`

**Target state:**
- A single generic `VoiceAgent` factory that reads voice config + `SOUL.md` from the data directory
- Python files only for voices that need custom behavior (custom providers, non-standard lifecycle)
- New voices are added by creating a config section + `SOUL.md`, not a `.py` file

This is already documented as "Declarative (P1+)" in [`docs/voices/voice-agent.md`](../voices/voice-agent.md). The P0 hand-coded voices were expedient for the build week; the declarative model is the production direction.

**Why:**
- A voice's identity comes from its SOUL prompt, role, and tool access — not its Python class
- Adding a voice should be a config change, not a code change
- The 3 existing subclasses are structurally identical (profile + init + factory function)
- Hot reload already handles data file changes, so declarative voices reload on SOUL edit without restart
