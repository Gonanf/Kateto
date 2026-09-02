---
id: 79
title: "Plugin wait_idle barrier and TTS speech turn synchronization"
severity: Alta
status: resolved
component: kateto/core/plugin.py
resolved: 2026-09-01
---

## 79. Plugin wait_idle barrier and TTS speech turn synchronization

**Severidad:** Alta
**Componente:** `kateto/core/plugin.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/bate_debate/orchestrator.py`

### Descripción

1. En debates y modos turn-based con TTS, el orquestador cambiaba de orador de manera prematura antes de que el orador actual terminara de hablar por los altavoces.
2. Después de los dos primeros turnos (al ocurrir una objeción o interrupción), el TTS se silenciaba por completo y dejaba de hablar por el resto del debate.

### Causa

1. **Desacoplamiento entre LLM y Audio:**
   El orquestador avanzaba guiándose únicamente por la finalización de los tokens del LLM (que tardan ~1-2s). La función `_wait_for_speech_finish` dependía de un polling con timeout de 2.5s que expiraba mientras EdgeTTS aún estaba negociando con el servidor remoto y decodificando audio, asumiendo falsamente que el reproductor ya estaba inactivo.
2. **Falta de barrera de sincronización en la clase base:**
   No existía en `Plugin` un método determinista para esperar que un plugin y sus colas/tareas en vuelo queden ociosas (`wait_idle`).
3. **Bloqueo zombi por interrupción en EdgeTTS:**
   En `EdgeTTSAudioOutput`, una interrupción marcaba `_interrupted = True`, pero `on_text_chunk` descartaba todo texto subsiguiente sin restablecer la bandera al inicio de un nuevo turno (`sequence == 0` o nuevo orador). Además, eventos inmediatos como `interrupt` quedaban encolados al final de una cola FIFO en lugar de ejecutarse de inmediato.

### Solución aplicada

1. **Barrera `wait_idle` en la clase base `Plugin` (`kateto/core/plugin.py`):**
   - Se introdujo `self._idle_event = asyncio.Event()`, la propiedad `is_busy` y el método asíncrono `wait_idle(timeout=None)`.
   - Se optimizó `_enqueue` para despachar `immediate_events` (como `"interrupt"`) en una tarea inmediata sin esperar en la cola FIFO, permitiendo que las interrupciones se procesen en el mismo tick del event loop.
2. **Sincronización en `EdgeTTSAudioOutput` y `AudioOutputPlayer`:**
   - Se implementó la propiedad `is_busy` para considerar tareas activas de síntesis, pipelines de mezcla y buffers de hardware en sonido.
   - En `EdgeTTSAudioOutput`, se restablece `_interrupted = False` automáticamente cuando comienza un nuevo turno o cambia de orador.
   - Tanto la finalización normal como las interrupciones disparan `_idle_event.set()`, liberando de inmediato las esperas activas.
3. **Orquestador sincronizado por barrera:**
   - En `_wait_for_speech_finish` (`kateto/plugins/bate_debate/orchestrator.py`), se reemplazaron los timers ciegos por `await tts_plugin.wait_idle()` seguido de `await player.wait_idle()`.

**Archivos:** `kateto/core/plugin.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/tests/test_plugin_wait_idle.py`
