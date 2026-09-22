---
id: 73
title: "Debate TTS repetición de voz en navegador y TimeoutError en generate_turn"
severity: Alta
status: resolved
component: kateto/plugins/bate_debate/orchestrator.py, kateto/plugins/visual_overlay/web/courtroom.html
resolved: 2026-08-31
---

## 73. Debate TTS repetición de voz en navegador y TimeoutError en generate_turn

**Severidad:** Alta  
**Componente:** [`kateto/plugins/bate_debate/orchestrator.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/bate_debate/orchestrator.py), [`kateto/plugins/visual_overlay/web/courtroom.html`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/web/courtroom.html)

### Descripción

1. Al ejecutarse un debate, cada argumento o turno era sintetizado y reproducido dos veces consecutivas: una a través del motor de audio de backend (`audio_output_player`), y simultáneamente una segunda vez por el navegador mediante la Web Speech API de `courtroom.html`.
2. Durante turnos de argumentación o consideración de objeción con modelos locales más lentos, `EventDebateClient.generate_turn` lanzaba `TimeoutError` tras 35 segundos, haciendo crashear la aplicación ASGI (`asyncio.CancelledError` en websockets).

### Impacto

- El usuario escuchaba un eco/repetición molesta de cada frase hablada en el courtroom.
- El debate se interrumpía abruptamente con un traceback de `TimeoutError` cuando el LLM requería más tiempo para prefill o generación.

### Causa

- En `courtroom.html`, la función `speakDebateTurn(text, voice_id)` llamaba a `window.speechSynthesis.speak(utter)` para cada evento `debate` recibido por WebSocket, ignorando que el backend ya reproduce el audio por los parlantes.
- En `orchestrator.py`:
  - `generate_turn` tenía un timeout rígido de 35s y filtraba `text_chunk` y `voice_idle` sin `casefold()`.
  - La verificación de `voice_idle` exigía `if chunks:`, de modo que si los chunks no habían llegado o no coincidían en casing, ignoraba el fin de turno y esperaba hasta el timeout.
  - `_consider_objection` llamaba a `_speak_turn`, emitiendo un turno de habla en el bus que se intentaba reproducir por TTS incluso cuando la respuesta era `NO_OBJECION`.

### Solución aplicada

1. Se eliminó la invocación a `speakDebateTurn` en [`courtroom.html`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/web/courtroom.html). El audio se emite exclusivamente desde el backend Kateto.
2. En [`orchestrator.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/bate_debate/orchestrator.py):
  - Se implementó comparación case-insensitive (`casefold()`) para `text_chunk` y `voice_idle`.
  - Al recibir `voice_idle` se despierta de inmediato `done_event` sin bloquearse.
  - Se incrementó el timeout por defecto de 35s a 120s y se capturó `TimeoutError` para devolver el texto acumulado sin crashear.
  - Se modificó `_consider_objection` para evaluar el contraargumento de forma silenciosa vía `_speak` (sin emitir al bus de TTS), emitiendo el chunk de audio únicamente cuando se concreta una objeción real.

**Archivos:** `kateto/plugins/bate_debate/orchestrator.py`, `kateto/plugins/visual_overlay/web/courtroom.html`
