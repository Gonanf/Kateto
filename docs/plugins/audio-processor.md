# Audio Processor Plugins

Process audio emitted by Audio Inputs. Can be **chained** by capabilities.

## Plugins

### `audio_processor_whisper` (P0)
Transcription using `whisper-large-v3-turbo` via local HTTP server (whisper.cpp).

**Receives:** `audio_chunk` → `AudioData`
**Emits:** `transcription` → `TranscriptionData`

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
