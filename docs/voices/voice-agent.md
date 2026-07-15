# VoiceAgent Base Class

Inherits from `Plugin`. The base class for all voice agents.

```python
class VoiceAgent(Plugin):
    capabilities = ["voice", "agent"]

    async def generate(self, prompt: str) -> AsyncGenerator[str, None]: ...
    async def add_to_queue(self, prompt: str): ...
    async def interrupt(): ...
```

## Generation

- `generate()` is an **async generator** — produces tokens in streaming mode
- The LLM is called via HTTP using the **OpenAI Python SDK**, compatible with both the OpenAI API and llama.cpp (which exposes an OpenAI-compatible API)

## Processing

Voices are **batch** plugins: they accumulate events in their queue and only process when they receive a `generate` event (dispatched by an Executor, typically the Classifier).

## Idle Detection

When the LLM returns an end-of-text token, the voice emits a `voice_idle` event. This signal is used by:

- **Workflow engine**: auto-advance to next phase
- **TODO Executor**: check for pending work and prompt continuation
- **TUI**: display voice state (speaking / idle / thinking)

## Voice Creation

### Manual (P0)
Python file with a class inheriting from `VoiceAgent`. Required for voices with custom logic (Jane, Doktor, Conquest).

### Declarative (P1+)
Directory `Voices/{name}/` with `SOUL.md` and optional workflow files. No Python subclass needed — the manager creates a generic `VoiceAgent` with the SOUL as system prompt. Used for simpler voices (Narrador, Susurrante, all P2 voices).

```
Voices/
├── Jane/
│   ├── SOUL.md
│   ├── MEMORIES.md
│   ├── JOURNAL.md
│   ├── training/          # VoiceClassifier training data
│   └── workflows/
├── Doktor/
│   └── workflows/
└── ...
```

## Coordination Between Voices

When an agent generates text:
1. It emits an event for **TTS** to play the audio
2. It emits a **separate event** for other agents to know what was said (skips self because self-delivery is OFF)

This allows each agent to stay aware of the conversation without a centralized history.

### Cross-Voice Requests (e.g., Jane → Informante)

1. Jane needs information → emits an event targeted at Informante or with "research" capability
2. Jane continues executing (non-blocking)
3. Informante receives the event, researches, emits response
4. Jane receives the response asynchronously when an Executor sends her a new `generate`

**Note:** Without an Executor to coordinate, Jane would block waiting. Executors (Classifier + TODO List) orchestrate these flows.
