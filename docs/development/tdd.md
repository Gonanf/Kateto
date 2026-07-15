# TDD & Development

## TDD Flow

```
RED   → Write a test that fails
GREEN → Write minimum code to pass the test
REFACTOR → Improve code while keeping tests green
```

The TDD cycle is mandatory for all development. No exceptions.

## Testing Strategy

### Unit Tests (Core)

| Area | Focus |
|---|---|
| Event Bus | Registration, dispatch, filtering, error handling |
| PluginManager | Lifecycle, enable/disable, hot-reload, singletons |
| Plugin base class | Initialization, queue processing, capabilities |
| Config | TOML parsing, validation, section injection |

### Framework

- `pytest` + `pytest-asyncio` for async test support

### Mocking

External HTTP servers are **NOT mocked** if local instances are available (whisper.cpp, llama.cpp, Zonos2.cpp, mmBERT). Tests can use the real servers because they run locally — no risk of damage or rate limiting.

### CI

Managed by the user.

## Project Structure

```
kateto/
├── SPEC.md
├── README.md
├── pyproject.toml
├── .env
├── kateto/
│   ├── __init__.py
│   ├── core/
│   │   ├── plugin.py         # Plugin base class
│   │   ├── manager.py        # PluginManager (singleton + event bus)
│   │   ├── event.py          # Event system (registration, dispatch)
│   │   ├── config.py         # TOML config loader
│   │   └── hot_reload.py     # Watchdog watcher
│   ├── plugins/
│   │   ├── audio_input/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   └── mic.py
│   │   ├── audio_processor/
│   │   │   ├── __init__.py
│   │   │   └── whisper.py
│   │   ├── audio_output/
│   │   │   ├── __init__.py
│   │   │   └── zonos.py
│   │   ├── executor/
│   │   │   ├── __init__.py
│   │   │   ├── classifier.py
│   │   │   ├── interrupt.py
│   │   │   ├── todo_list.py
│   │   │   └── voice_classifier.py
│   │   ├── connector/
│   │   │   ├── __init__.py
│   │   │   ├── calendar.py
│   │   │   ├── google_meet.py
│   │   │   └── cli.py
│   │   └── system/
│   │       ├── __init__.py
│   │       ├── tui.py
│   │       └── mcp_server.py
│   ├── voices/
│   │   ├── __init__.py
│   │   ├── base.py           # VoiceAgent class
│   │   ├── jane.py
│   │   ├── doktor.py
│   │   └── conquest.py
│   └── tests/
│       ├── __init__.py
│       ├── test_event_bus.py
│       ├── test_plugin_manager.py
│       └── test_audio_pipeline.py
├── config/kateto/
│   ├── config.toml
│   ├── voices/
│   │   ├── Jane/
│   │   │   ├── SOUL.md
│   │   │   ├── MEMORIES.md
│   │   │   ├── JOURNAL.md
│   │   │   ├── training/
│   │   │   └── workflows/
│   │   ├── Doktor/
│   │   │   └── workflows/
│   │   └── Conquest/
│   ├── workflows/
│   └── secrets/
│       └── .env
└── servers/              # Scripts to launch external servers
    ├── llama.cpp
    ├── whisper.cpp
    ├── mmbert/
    └── zonos2.cpp
```

## Default Servers

All run locally:
- **llama.cpp**: HTTP server for LLMs (OpenAI-compatible API)
- **whisper.cpp**: HTTP server for transcription
- **mmBERT** (GGUF on llama.cpp): Intent classifier (fine-tuned with custom dataset)
- **Zonos2.cpp / Zonos0.1.cpp**: TTS with speaker embeddings
- **qwenTTS.cpp** (postergated): Alternative TTS
