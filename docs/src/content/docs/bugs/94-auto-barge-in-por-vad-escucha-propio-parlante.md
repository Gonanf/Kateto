---
id: 94
title: "El micrófono escucha el propio parlante y el VAD auto-interrumpe el habla (falso barge-in)"
severity: Alta
status: resolved
component: kateto/plugins/audio_input/listener.py
resolved: 2026-09-18
---

## 94. El micrófono escucha el propio parlante y el VAD auto-interrumpe el habla (falso barge-in)

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_input/listener.py`

### Descripción

Con parlantes (no auriculares), la voz responde una palabra y se corta. Patrón repetido: whisper → clasificación → LLM 200 OK → una palabra audible → `child process ... returncode 255` (teardown de ffmpeg a mitad de frase). El micrófono capta la propia salida, el VAD dispara `voice_started` y `manager.interrupt(reason="voice_activity")` cancela la generación, el TTS y las lanes del player.

### Impacto

Respuestas truncadas a una palabra de forma intermitente; el `255` enmascara la causa real.

### Causa

- `_interrupt_playback` (`listener.py:183`) solo respeta `interrupt_on_vad` (default `True`); el flag `_playback_active` se setea en `on_audio_output` pero **nunca se consulta** — cualquier actividad VAD interrumpe, incluso con el turno propio sonando y sin cancelación de eco.
- Sin AEC ni headset, el barge-in no distingue al usuario del parlante.

### Posible solución

1. Workaround inmediato: `audio_input_mic.interrupt_on_vad = false` en user config, o usar auriculares.
2. Confirmar con el log: `[mic] Speech detected` entre el inicio de Jane y el corte, en silencio del usuario.
3. Fix real pendiente: gating con gracia/debounce del barge-in (p. ej. ignorar VAD con nivel/patrón de la propia salida), o AEC. Nótese que interrumpir al usuario hablando encima SÍ es el comportamiento correcto — solo hay que distinguirlo.

**Archivos:** `kateto/plugins/audio_input/listener.py`, `kateto/plugins/audio_input/base.py`

### Solución aplicada (2026-09-18, detalle en `FIX-94.md` + sección FIX-94b)

1. Gracia de onset de 800 ms (`barge_in_grace_ms`): VAD dentro de la ventana se
   ignora y difiere, sin perder el barge-in real que persiste más allá.
2. Stamping una sola vez por ventana de playback (antes se re-stampeaba en cada
   chunk del TTS y el barge-in quedaba imposible durante todo el playback).
3. Discriminador por nivel sin dependencias nuevas: el mic debe superar
   `playback_rms × barge_in_level_factor` (1.3) con habla sostenida
   ≥ `barge_in_min_speech_ms` (300 ms); logs `granted/denied` con los números.
4. Atribución de bleed: segmentos durante playback propio sin barge-in se
   descartan (no entran a Whisper); acumulación de turno (un `audio_chunk` por
   turno, `turn_silence_timeout` 2.0 s, `max_turn_secs` 30 s).
5. Segunda pasada (2026-09-18, detalle en `FIX-94.md` sección "Segunda pasada"):
   watchdog `playback_idle_timeout` (default 1.5 s, `0` lo deshabilita) — el
   `final=True` no es fiable (bug 97: el player pierde oraciones en cola tras
   el final), así que sin chunks de `audio_output` en esa ventana el listener
   reabre el mic (`reopening mic`) en vez de quedar sordo para siempre; y
   desacople del descarte respecto de `interrupt_on_vad` — el descarte depende
   solo de `_playback_active` + ausencia de barge-in, así con el workaround
   `interrupt_on_vad=false` el bleed tampoco entra al turno (antes Kateto se
   transcribía a sí misma).
