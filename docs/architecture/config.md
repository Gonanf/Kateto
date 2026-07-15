# Configuration

## Main Config: `config.toml`

A single TOML file. Each section header matches a plugin name, and the PluginManager injects only the relevant section into each plugin.

```toml
[kateto]
debug = true
hot_reload = true

[plugin.audio_input_mic]
enabled = true
device = "default"
silence_timeout = 3.0
interrupt_on_vad = true
vad_threshold = 0.5
interrupt_llm = true
interrupt_tts = true

[plugin.audio_processor_transcription]
enabled = true
model = "whisper"
endpoint = "http://localhost:8081"

[plugin.executor_classifier]
enabled = true
model_endpoint = "http://localhost:8082/mmbert"
context_window = 10

[voice.jane]
enabled = true
soul = "Voices/Jane/SOUL.md"
```

## Secrets: `.env`

API keys and credentials go in `.env`, **never** in `config.toml`.

```
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
OPENAI_API_KEY=xxx
```

Each connector reads its secrets from environment variables loaded from `.env`.

## Plugin-Specific Config

Each plugin receives only its own section from `config.toml`. The manager handles extraction and injection.

### Audio Input Mic Config

```toml
[plugin.audio_input_mic]
interrupt_on_vad = true
vad_threshold = 0.5         # Silero VAD sensitivity
interrupt_llm = true         # Interrupt LLM generation on VAD
interrupt_tts = true         # Interrupt TTS playback on VAD
silence_timeout = 3.0
```

## Config Directory

All configuration and mutable data lives in `config/kateto/`:

```
config/kateto/
├── config.toml              # Main configuration
├── voices/                  # Per-voice data
│   ├── Jane/
│   │   ├── SOUL.md
│   │   ├── JOURNAL.md
│   │   ├── MEMORIES.md
│   │   └── workflows/
│   ├── Doktor/
│   └── Conquest/
├── workflows/               # Global workflows
└── secrets/
    └── .env
```
