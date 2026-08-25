---
title: Tdd
description: Tdd — documentación de Kateto.
---

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
| PluginManager | Lifecycle, enable/disable, singletons |
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
├── pyproject.toml
├── kateto/
│   ├── __init__.py
│   ├── __main__.py          # Entrypoint: main() dispatches argv
│   ├── run_mode.py          # RuntimeOwner, RuntimeComponents assembly
│   ├── live.py              # build_event_runtime() — wires everything
│   ├── core/
│   │   ├── config.py        # TOML loading, bootstrap, ConfigPaths
│   │   ├── discovery.py     # Plugin/plugin discovery by directory
│   │   ├── event.py         # EventModel base, all event contracts
│   │   ├── exceptions.py
│   │   ├── manager.py       # PluginManager (singleton + event bus)
│   │   ├── plugin.py        # Plugin base class
│   │   ├── storage.py       # VoiceFileStore (path isolation)
│   │   ├── workflow.py      # WorkflowCatalog, WorkflowDefinition
│   │   └── workflow_engine.py # WorkflowEngine (runner)
│   ├── plugins/
│   │   ├── audio_input/
│   │   │   ├── base.py, capture.py, listener.py, mic.py, meet.py, silero.py
│   │   ├── audio_output/
│   │   │   ├── base.py, camb.py, edgetts.py, player.py, zonos.py
│   │   ├── audio_processor/
│   │   │   └── whisper.py
│   │   ├── executor/
│   │   │   ├── classifier.py, interrupt.py, todo_list.py, workflow_router.py
│   │   ├── connector/
│   │   │   ├── calendar.py, cli.py
│   │   ├── system/
│   │   │   ├── external_mcp.py, http_server.py, mcp_server.py, tui.py, voice_manager.py
│   │   ├── voice_soul_manager/
│   │   │   └── scheduler.py, updater.py
│   │   └── work/
│   │       └── backlog.py
│   ├── voices/
│   │   ├── base.py          # VoiceAgent (profile, memory, generation)
│   │   ├── factory.py       # create_voice(), VoiceProfile dict
│   │   ├── memory.py        # VoiceMemory
│   │   ├── skills.py        # load_skills()
│   │   └── tools.py         # VoiceToolExecutor (built-in + user tools)
│   ├── providers/           # LLM, TTS, classifier HTTP providers
│   └── tests/               # 157 tests, pytest-asyncio
├── config/
│   └── defaults/            # Bootstrap template (config.toml, voices, skills)
├── docs/
│   └── ...
└── script/
    └── qa/                  # Fixture scripts, acceptance.py
```

## Default Servers

All run locally:
- **llama.cpp**: HTTP server for LLMs (OpenAI-compatible API)
- **whisper.cpp**: HTTP server for transcription
- **mmBERT** (GGUF on llama.cpp): Intent classifier (fine-tuned with custom dataset)
- **Zonos2.cpp / Zonos0.1.cpp**: TTS with speaker embeddings
- **qwenTTS.cpp** (postergated): Alternative TTS
