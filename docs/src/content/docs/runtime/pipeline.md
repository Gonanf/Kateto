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

## Knobs del listener (`audio_input_mic`)

| Knob | Default | Efecto |
|---|---|---|
| `barge_in_grace_ms` | `800.0` | VAD dentro de la ventana de playback propio se difiere |
| `barge_in_level_factor` | `1.3` | El mic debe superar `playback_rms × factor` para cortar |
| `barge_in_min_speech_ms` | `300.0` | Habla sostenida mínima para el barge-in real |
| `playback_idle_timeout` | `1.5` (`0` lo deshabilita) | Sin `audio_output` en esa ventana → playback terminado (el `final=True` no es fiable, bug 97) |
| `turn_silence_timeout` | `2.0` | Silencio continuo que cierra el turno (un `audio_chunk` por turno) |
| `max_turn_secs` | `30.0` | Techo del buffer de turno |
