---
id: 106
title: "Una generación por fragmento de Whisper — falta cancelación/gating downstream del turno"
severity: Alta
status: resolved
component: kateto/plugins/audio_input/listener.py
resolved: 2026-09-18
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

### Solución aplicada (2026-09-18, detalle en `FIX-94.md` sección "Segunda pasada")

- Acumulación de turno en el listener: los segmentos consecutivos se anexan al
  `_turn_buffer` y se emite **un solo** `audio_chunk` por turno (fin de turno =
  silencio ≥ `turn_silence_timeout`, default 2.0 s; cap `max_turn_secs`, default
  30 s) → una sola pasada de Whisper por turno, un solo `generate` downstream.
  Cubierto por `kateto/tests/test_audio_turn_chain.py` (3 segmentos cercanos →
  1 `transcribe` + 1 `generate`; 2 turnos separados → 2 + 2; bleed en playback
  → 0 `transcribe`).
- Señal `interrupt(reason="user_turn")` al abrir un turno de usuario (solo cuando
  `interrupt_on_vad` es false, donde antes no había ninguna señal de corte;
  con VAD el `voice_activity` ya cubre el caso). Reusa los handlers existentes
  sin cambiar firmas ni contratos: `VoiceAgent.on_interrupt` cancela
  `_generation_task` y purga `token_queue`/`pcm_queue` (las reemplaza por vacías);
  EdgeTTS `on_interrupt` corta el stream (`_cancel_stream`) y purga su cola;
  el player `on_interrupt` limpia las lanes del turno (`_pop_lane(rescue=False)`).
  Cubierto por `test_new_user_turn_emits_user_turn_interrupt_when_vad_interrupt_disabled`
  y `test_new_user_turn_cancels_inflight_generation_and_purges_queues`.

### Posible solución (pendiente, downstream)

1. Cancelar la generación/TTS en curso cuando llega una transcripción nueva del
   mismo turno (interrupción inmediata) en vez de encolar otra generación.
2. Opcional: gatear `classifier → generate` hasta el fin de turno explícito.
3. Cerrar el bug 58 del lado provider si sigue transcribiendo de más.

**Archivos:** `kateto/plugins/audio_input/listener.py`, `kateto/plugins/audio_input/base.py`, `docs/src/content/docs/bugs/58-whisper-transcribes-per-chunk.md`
