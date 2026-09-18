---
id: 118
title: "Mensajes ignorados por el clasificador: quedan sin marca y el LLM los contesta en el turno siguiente"
severity: Alta
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-18
---

## 118. Mensajes ignorados por el clasificador: quedan sin marca y el LLM los contesta en el turno siguiente

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`

### Descripción

Reporte textual del usuario: *"Los mensajes ignorados por el clasificador son respondidos
constantemente por mensajes posteriores de los LLM. Si yo digo 'Gracias.', entonces el LLM
debería tener en el mensaje ese 'Gracias.' pero también saber que no debe responderlo si lo
ve como último mensaje de usuario."*

### Impacto

El usuario dice algo que el clasificador descarta ("Gracias.") y no recibe respuesta inmediata
—correcto—, pero en el turno siguiente (narración de visión, follow-up o pedido real) el modelo
contesta ese "Gracias." viejo como si fuera el último pedido.

### Causa

`TurnGate.on_classification` guardaba el texto ignorado en `_ignored` y `decide()` lo descartaba
(`_consume_ignored`), pero eso sólo evita **disparar** un turno con ese texto: no tocaba el
historial. `VoiceAgent._enqueue` registraba **todas** las transcripciones vía `_remember_event`
como `user: Gracias.` sin marca. El siguiente `_messages_for` mandaba ese `user` en claro como
último mensaje de usuario y el modelo lo contestaba.

### Solución aplicada

- La transcripción ignorada queda en el historial con el texto original visible pero prefijada:
  `[IGNORADO POR EL CLASIFICADOR — NO RESPONDER] Gracias.`
- Elección: prefijo en el **contenido** del mensaje `user`, no mensaje `system` aparte. El camino
  pydantic (`_pydantic_agent_loop`) filtra el historial a roles `("assistant", "user")` y un
  `system` intercalado se descartaría; el prefijo sobrevive en los dos caminos (proveedor
  directo y pydantic) y se ve en el prompt final.
- La marca vive sólo en el historial por turno (`_event_messages`, parte volátil): el prompt
  estable congelado (`voices/context.py::stable_prompt`) no cambia.
- Sin duplicar el texto (se reescribe la entrada existente, no se agrega otra) y sin perder el
  descarte: `TurnGate._consume_ignored` sigue devolviendo `Decision.DISCARD` si el texto vuelve
  solo. `TurnGate.on_classification` y las voces comparten `is_ignored_category()` de
  `kateto/core/event.py`, que cubre `IGNORE_SELF_TALK`, `IGNORE_THIRD_PARTY` y cualquier futura
  `IGNORE_*` del enum `Classification`.
- Detalle de implementación: las voces reciben `classification` vía el nuevo `on_classification`
  (suscripción) pero la marca se aplica sincrónicamente en `VoiceAgent._enqueue`, porque los
  handlers de voz son batch (`streaming=False`, trigger `generate`) y el handler diferido
  llegaría tarde. Funciona con y sin tools/agente: ambos caminos comparten `_messages_for`.

**Archivos:** `kateto/core/event.py`, `kateto/plugins/system/turn_gate.py`, `kateto/voices/base.py`, `kateto/tests/test_ignored_transcript_mark.py`
