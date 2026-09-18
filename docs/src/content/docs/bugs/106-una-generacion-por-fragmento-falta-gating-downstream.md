---
id: 106
title: "Una generación por fragmento de Whisper — falta cancelación/gating downstream del turno"
severity: Alta
status: open
component: kateto/plugins/audio_input/listener.py
---

## 106. Una generación por fragmento de Whisper — falta cancelación/gating downstream del turno

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_input/listener.py` (origen), `whisper → classifier → generate` (resto pendiente)

### Descripción

Cada fragmento que Whisper.cpp transcribe (muchas veces parte el texto como si
la frase hubiera terminado) dispara una petición de generación. Lo reportado:
mientras el usuario habla se genera una respuesta por fragmento en vez de
acumular el turno y generar una sola vez al final (o cancelar lo generado si el
usuario sigue hablando).

### Impacto

Respuestas generadas a partir de media frase, N inferencias LLM/TTS por turno,
y la sensación de que Kateto "habla sin importarle si yo estoy hablando".

### Causa

`VadSegmenter.consume` cerraba un segmento por cada pausa ≥ `silence_timeout` y
`_emit_segment` emitía un `audio_chunk` por segmento → `whisper → transcription →
classifier → generate → speak`, una vez por fragmento. Ver bug 58
(`58-whisper-transcribes-per-chunk.md`) para el lado del provider.

### Solución parcial aplicada (listener, 2026-09-18, ver `FIX-94.md` sección FIX-94b)

- El listener acumula segmentos consecutivos y emite **un solo** `audio_chunk`
  por turno (fin de turno = silencio ≥ `turn_silence_timeout`, default 2.0 s;
  cap `max_turn_secs`, default 30 s) → una sola pasada de Whisper por turno.
- Mientras el playback propio está activo sin barge-in real, el segmento se
  atribuye al bleed y se descarta (no entra al buffer de turno).

### Posible solución (pendiente, downstream)

1. Cancelar la generación/TTS en curso cuando llega una transcripción nueva del
   mismo turno (interrupción inmediata) en vez de encolar otra generación.
2. Opcional: gatear `classifier → generate` hasta el fin de turno explícito.
3. Cerrar el bug 58 del lado provider si sigue transcribiendo de más.

**Archivos:** `kateto/plugins/audio_input/listener.py`, `kateto/plugins/audio_input/base.py`, `docs/src/content/docs/bugs/58-whisper-transcribes-per-chunk.md`
