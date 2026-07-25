# Design Decisions

## Dependencies Are Intentional

All runtime dependencies are deliberate choices, not convenience bloat:

| Dependency | Why, not what stdlib replacement |
|---|---|
| `httpx` | Async HTTP throughout. `urllib` is sync-only without thread-pool hacks. Every provider (Whisper, LLM, TTS, classifier) streams async. |
| `numpy` | Audio buffer manipulation in capture pipeline. `array('h')` works for trivial cases but numpy handles resampling, normalization, and the reshape/view patterns the audio pipeline needs. |
| `python-dotenv` | Explicit .env loading with `.env` precedence rules, quoting, and comment handling. Stdlib inline parsing drifts on edge cases. |
| `anyio` | Async compatibility layer. Provides consistent async primitives across trio/asyncio backends. |
| `pydantic` | Boundary validation for every external input (config files, MCP requests, SSE streams, plugin events). Pydantic `ValidationError` provides structured error context. `dataclasses` throw bare `TypeError` with no trace of which field failed. |
| `torch` | Silero VAD requires PyTorch runtime. Direct pin acknowledges this even though `silero-vad` pulls it transitively — makes the dependency explicit. |
| `mcp` | Model Context Protocol server implements the MCP spec. No stdlib equivalent. |
| `sounddevice` | Cross-platform audio capture/playback via PortAudio. No stdlib API for audio device access. |
| `textual` | Terminal UI framework. No stdlib equivalent for async TUI. |
| `openai` | OpenAI-compatible LLM API (works with llama.cpp, OpenAI, and compatible servers). No stdlib equivalent. |
| `google-auth-oauthlib` | Google Calendar OAuth2 flow. Conditional import via `importlib`, not loaded unless calendar connector is configured. |

**Guiding principle:** Zero new dependencies unless they pull their weight. The existing set is reviewed and approved. No dep is removed without a concrete (not theoretical) stdlib alternative that covers the same edge cases.

## Declarative Voice Generation (Completed)

Voice agents are created from configuration + data files via a factory, not hand-written Python subclasses.

**Current state (completed migration):**
- `kateto/voices/factory.py` reads `VoiceProfile` dicts from `_PROFILES` to create voices
- No Python subclass scanning — all 3 voices (Jane, Doktor, Conquest) are declarative
- New voices are added by creating a config section + `SOUL.md` + `VoiceProfile` entry

**Why:**
- A voice's identity comes from its SOUL prompt, role, and tool access — not its Python class
- Adding a voice should be a config change, not a code change
- The factory approach is structurally simpler and testable
