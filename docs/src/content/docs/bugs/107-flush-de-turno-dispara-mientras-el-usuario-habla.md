---
id: 107
title: "El flush de turno dispara mientras el usuario habla"
severity: Alta
status: resolved
component: kateto/plugins/audio_input/listener.py
resolved: 2026-09-18
---

## 107. El flush de turno dispara mientras el usuario habla

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_input/listener.py`

### Descripción

`_rearm_turn_flush()` se llamaba sólo desde `_handle_closed_segment()` (al cerrar
un segmento). Cuando el usuario retomaba el habla dentro de la ventana de
`turn_silence_timeout`, el drain loop no cancelaba el task pendiente: el
`voice_started` sólo logueaba, prendía el indicador de grabación y llamaba a
`_interrupt_playback(mic_rms)`. El timer disparaba igual →
`_flush_turn()` → `_emit_segment(parcial)` → whisper → transcription →
classifier → generate. La voz contestaba un mensaje incompleto mientras el
usuario seguía hablando ("hablan pisándome y responden a mensajes incompletos").
La acumulación funcionaba cuando el usuario callaba, pero se rompía al reanudar
antes de que venciera el timer.

### Impacto

Respuestas a media frase mientras el usuario sigue hablando; un turno largo se
fragmenta en N `audio_chunk` → N pasadas de Whisper → N `generate`.

### Causa

Falta de cancelación del `_turn_flush_task` pendiente al detectar habla nueva en
`_drain_callback_queue`. Verificada leyendo el código (no hipótesis).

### Solución aplicada (2026-09-18, detalle en `FIX-94.md` sección "FIX-94e")

- Al detectar habla del usuario en el drain loop (con `_playback_active` en
  falso, o sea habla real y no bleed propio), se cancela el task pendiente y se
  loguea `[mic] turn flush cancelled: user resumed speaking`. No se re-arma
  hasta que cierra el próximo segmento (`_handle_closed_segment` ya lo re-arma).
- El cap duro `max_turn_secs` sigue forzando el flush en `_handle_closed_segment`
  (`reason=max_turn`); la cancelación en `disable()` y la guarda
  `self._turn_flush_task is current_task()` en `_turn_flush_later()` se mantienen.
- Diagnóstico al emitir: `[mic] turn flush reason=silence|max_turn
  segments=N buffered_ms=M` (segmentos acumulados y ms en buffer + motivo).
- Knob nuevo `turn_hold_ms` (default **0** = comportamiento actual): vencido
  `turn_silence_timeout`, espera ese extra antes de emitir; si vuelve el habla
  en ese extra, cancela y sigue acumulando.

**Archivos:** `kateto/plugins/audio_input/listener.py`, `kateto/plugins/audio_input/base.py`, `kateto/tests/test_audio_turn_flush.py`
