---
id: 68
title: "Debate CLI sin límite max_tokens, advertencia de tareas sin cerrar en ^C y estado del courtroom desconectado"
severity: Media
status: resolved
component: kateto/cli/commands.py, kateto/plugins/visual_overlay/
resolved: 2026-08-29
---

## 68. Debate CLI sin límite max_tokens, advertencia de tareas sin cerrar en ^C y estado del courtroom desconectado

**Severidad:** Media
**Componente:** `kateto/cli/commands.py`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/system/http_server.py`

### Descripción

Al ejecutar `kateto debate --overlay`:
1. El proveedor de LLM local (`OpenAICompatibleProvider`) no recibía `max_tokens`, permitiendo respuestas descontroladas en modelos sin EOS estricto que provocaban que el debate se quedara colgado en turnos de refutación (`_rebuttal`).
2. Al cancelar con `^C`, la tarea interna del cliente WebSocket no se cerraba limpiamente, disparando `Task was destroyed but it is pending!` y `RuntimeWarning: coroutine 'Connection.close' was never awaited`.
3. Al desconectarse o recargar la página `/courtroom`, el estado visual del tribunal se perdía por completo y no intentaba reconectar.
4. El courtroom mostraba únicamente el rol (`Adversaria`) en vez del nombre de la voz (`Whisperer (Adversaria)`), y la síntesis de voz (Web Speech API) no reproducía audio por defecto.

### Impacto

- Debates colgados indefinidamente en modelos locales.
- Mensajes de error y corrutinas desatendidas en consola al interrumpir.
- Experiencia de usuario rota en el visual overlay y en el tribunal.

### Causa

- `_real_provider_factory()` inicializaba `OpenAICompatibleProvider` sin `max_tokens`.
- `_Broadcaster.close()` detenía el bucle de eventos sin esperar el cierre de la corrutina de WebSocket ni cancelar las subtareas.
- `http_server.py` y `courtroom.html` carecían de retención de estado y ciclo de auto-reconexión.
- `courtroom.html` usaba `ROLE_LABEL[role]` directo y `enableTts: false`.

### Solución aplicada

1. Se añadió `max_tokens=256` (configurable por `KATETO_LLM_MAX_TOKENS`) en `_real_provider_factory()`.
2. Se implementó un cierre limpio en `_Broadcaster.close()`, cancelando y esperando todas las tareas antes de detener el bucle.
3. Se añadió impresión en tiempo real a `stdout` en `on_speak`.
4. Se agregó persistencia de estado de debate en `VisualOverlayPlugin`, endpoint `/api/courtroom/state`, y auto-reconexión con restauración automática en `courtroom.html`.
5. Se activó TTS por defecto (`enableTts: true`) con desbloqueo de contexto de audio por interacción y prevención de recolección de basura de `SpeechSynthesisUtterance`.
6. Se formatearon los nombres de las voces en pantalla y en audio (`Whisperer (Adversaria)`, `Jane (Judge)`, etc.).

**Archivos:** `kateto/cli/commands.py`, `kateto/plugins/system/http_server.py`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/visual_overlay/web/kateto-avatar.js`
