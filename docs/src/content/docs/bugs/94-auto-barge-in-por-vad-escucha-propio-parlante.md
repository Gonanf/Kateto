---
id: 94
title: "El micrófono escucha el propio parlante y el VAD auto-interrumpe el habla (falso barge-in)"
severity: Alta
status: open
component: kateto/plugins/audio_input/listener.py
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
