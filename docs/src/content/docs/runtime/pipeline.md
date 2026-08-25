---
title: Pipeline de audio end-to-end
description: "El flujo real de voz: micrófono → VAD → Whisper → clasificador → VoiceManager → voz → TTS → mixer."
---

# Pipeline de audio

Flujo REAL de voz (verificado en código):

```
mic/listener (VAD Silero) → audio_chunk
→ audio_processor/whisper (transcripción) → transcription
→ executor/classifier (EXECUTE/IGNORE) → generate
→ system/voice_manager (elige voz) → speak
→ voices/base.py VoiceAgent (stream tokens a token_queue)
→ audio_output TTS → pcm_queue
→ audio_output/player (mixer) → sonido
```

## Data plane vs Control plane

- **Data plane:** tokens de LLM y PCM de TTS van por canal directo (async generator / cola), NUNCA por `emit()` por token.
- **Control plane:** el bus solo transporta `generate`, `speak`, `interrupt`, `idle`, `speaking_state`.

## Interrupción

El `interrupt` NO cancela tareas ya encoladas — solo frena el consumidor. Para purgar: reemplazar las colas del pipeline por vacías en `on_interrupt` (`pcm_queue = asyncio.Queue()`).
