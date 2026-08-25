---
title: Config
description: Config — documentación de Kateto.
---

# Configuration

## Main Config: `config.toml`

A single TOML file. Each section header matches a plugin name, and the PluginManager injects only the relevant section into each plugin. Defaults live in `config/defaults/config.toml` and bootstrap copies missing keys to the user config dir (`~/.config/kateto/`) — user config is authoritative and is never overwritten.

```toml
[kateto]
debug = true

[plugin.audio_input_mic]
enabled = true
device = "default"
silence_timeout = 3.0
interrupt_on_vad = true
vad_threshold = 0.5
interrupt_llm = true
interrupt_tts = true

[plugin.audio_processor_whisper]
enabled = true
# HTTP mode (default): talk to a whisper.cpp server
endpoint = "http://127.0.0.1:8090"
# Local mode (self-contained): invoke the binary directly, no server
# command = "/home/chaos/proyectos/whisper.cpp/build/bin/whisper-cli"
# model = "/home/chaos/proyectos/whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin"
# args = ["--language", "es"]

[plugin.executor_classifier]
enabled = true
# HTTP mode (default): OpenAI-compatible endpoint
endpoint = "http://127.0.0.1:8091/v1"
# Local mode: run the binary per call (LLM file path in `model`)
# command = "/usr/bin/llama-cli"
# model = "/home/chaos/models/classifier.gguf"

[plugin.voice_llm]
enabled = true
endpoint = "http://127.0.0.1:11434/v1"   # llama.cpp / OpenAI-compatible
model = "KatetoTalker"

[voice.jane]
enabled = true
stream = true          # streaming generation by default (VoiceSettings default is True)
max_tokens = 4096
retries = 2
timeout = 600
```

## Local (self-contained) mode

Kateto can run the whisper and classifier backends **without any HTTP server** by
setting `command` on the plugin section: the `LocalCommandProvider`
(`kateto/providers/_local.py`) spawns the binary per call and parses its output.
`model` is interpreted as a model-file path in this mode. The voice LLM is
HTTP-only today (OpenAI-compatible endpoint); a local subprocess path for the
LLM is a future option.

## Secrets: `.env`

API keys and credentials go in `.env` (or `secrets/.env`), never in `config.toml`.
Config values can reference them with `env:KEY_NAME`. `kateto doctor` and
`kateto setup` handle discovery/masking of keys.

## UI

The Textual TUI is deprecated. The Dashboard (Nuxt) talks to the FastAPI +
WebSocket server in `kateto/plugins/system/http_server.py` (port 8080 default,
also serves the visual overlay). The CLI (`kateto`) is for setup/ops (setup,
doctor, config check, run, install) — it is not a TUI and does not yet expose
every plugin setting; that surface belongs to the Dashboard.

## Plugin-Specific Config

Each plugin receives only its own section from `config.toml`. The manager
handles extraction and injection. See `config/defaults/config.toml` for the
full current list of plugin sections.
