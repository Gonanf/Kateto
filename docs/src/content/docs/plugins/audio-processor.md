---
title: Audio Processor
description: Audio Processor — documentación de Kateto.
---

# Audio Processor Plugins

Process audio emitted by Audio Inputs. Can be **chained** by capabilities.

## Plugins

### `audio_processor_whisper` (P0)
Transcription using `whisper-large-v3-turbo` via local HTTP server (whisper.cpp).

**Receives:** `audio_chunk` → `AudioData`
**Emits:** `transcription` → `TranscriptionData`

### `audio_processor_parakeet` (P1)
Local transcription via **parakeet (CrispASR)** — an alternative engine to Whisper.
Same boundary (`transcribe` capability), so **keep only one of the two enabled**
or every chunk gets transcribed twice.

**Receives:** `audio_chunk` → `AudioData`
**Emits:** `transcription` → `TranscriptionData`

Config (`[plugin.audio_processor_parakeet]`):
- `backend` — transport: `server` (default) | `cli` | `stream`.
  - `server` talks to an externally-launched CrispASR `--server` process (model
    resident → per-turn cost is proportional to the audio). The process must be up
    **before** enabling; `enable()` probes `/health` and `transcribe()` fail-opens if
    it is unreachable. Launch command (ultra model, Vulkan dev 1):
    ```
    /run/media/chaos/secundario/proyectos/crispasr/crispasr-linux-x86_64-vulkan/crispasr \
        --server --host 127.0.0.1 --port 8098 \
        -m /run/media/chaos/secundario/proyectos/redux-gguf/models/parakeet-ultra-q8_0.gguf \
        --backend parakeet --gpu-backend vulkan -dev 1
    ```
  - `cli` spawns the binary per invocation (full model load each turn).
  - `stream` opens the binary once in `--stream --stream-json` mode and feeds raw
    PCM per `audio_chunk` (live `partial`s + `final`, same `transcription` event
    with `TranscriptionData.partial`). Tuning: `stream_step_ms` (500),
    `stream_final_on_silence_ms` (600), `stream_max_restarts` (3),
    `stream_final_wait_s` (30.0). The server `--ws-port` WebSocket answers
    `{"error":"failed to open stream (whisper-only today)"}` for parakeet, so the
    child process is the streaming path (see `ASR-PARAKEET.md`).
- `motor = "ultra" | "redux"` — engine profile. With `cli` it picks the model
  (`parakeet-ultra-q8_0.gguf` / `parakeet-redux-q8_0.gguf`); with `server` it is
  informational only (the server holds its model).
- `host` / `port` — server endpoint (`127.0.0.1:8098` default).
- `language` — forced language (e.g. `es`, `en`), omitted when unset.
- `timeout` — per-transcription timeout (server can hang).
- `bin` / `model` / `gpu_backend` / `device` — CLI-only overrides (ignored with
  `backend = "server"`). `gpu_backend` is the GPU flag (`--gpu-backend`).
- `ventana` / `solape` — accepted for config parity but **not implemented**.

**Fail-open:** a missing server/binary or a hang is logged and yields no
transcription event instead of taking the runtime down.

### `audio_processor_qwen` (P2 — Postergated)
Alternative transcription using QwenASR. Postergated.

### `audio_processor_diarize` (P2 — Postergated)
Speaker diarization. Postergated.

## Chaining

Audio processors are chainable by capabilities:

```
Audio Input → Whisper (transcribe)
Audio Input → Diarize → Whisper (transcribe + diarize)
```

Each processor emits events and the next in the chain receives them if it has the appropriate capabilities.
