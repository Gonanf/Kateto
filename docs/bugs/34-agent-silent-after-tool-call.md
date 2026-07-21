---
id: 34
title: "Voice agent drops final response after tool calls"
severity: Alta
status: resolved
component: kateto/voices/base.py
resolved: 2026-07-21
---

## 34. Voice agent drops final response after tool calls

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`

### Descripción

En ocasiones una voz ejecutaba una o más herramientas y después no respondía
al usuario. El evento final del modelo podía llegar como un `AgentResponse`
normal, sin nuevos `tool_calls`.

### Impacto

La respuesta quedaba ausente del bus de eventos y, si además fallaba la
solicitud siguiente al proveedor, la voz podía permanecer en estado `thinking`
o `talking`.

### Causa

El ciclo de agente en modo streaming solo procesaba `StreamToken` y
`AgentResponse` que contenían `tool_calls`; descartaba silenciosamente un
`AgentResponse` final con texto. Además, la emisión de `voice_idle` estaba
después del ciclo, por lo que una excepción del proveedor o una cancelación
impedía limpiar el estado de la voz.

### Solución aplicada

El ciclo ahora entrega el texto de un `AgentResponse` final y termina esa
iteración de generación. La limpieza de `voice_idle` y `VoiceStatus.IDLE` se
ejecuta en `finally`, incluso si una herramienta o el proveedor falla.

### Archivos

`kateto/voices/base.py`, `kateto/tests/test_voice_history.py`
