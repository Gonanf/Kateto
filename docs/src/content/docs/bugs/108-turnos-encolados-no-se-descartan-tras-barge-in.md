---
id: 108
title: "Turnos encolados no se descartan tras un barge-in del usuario"
severity: Alta
status: resolved
component: kateto/plugins/system/turn_gate.py
resolved: 2026-09-18
---

## 108. Turnos encolados no se descartan tras un barge-in del usuario

**Severidad:** Alta
**Componente:** `kateto/plugins/system/turn_gate.py`

### Descripción

Reporte textual del usuario: *"Si le hablé, y se calló, solo que se acumuló mensajes y me habló después."*
El barge-in sí funcionaba (cortaba la generación en vuelo y purgaba las colas del
pipeline), pero los turnos que quedaron **encolados** se contestaban después, uno atrás del otro.

### Impacto

Tras interrumpir a la voz, el usuario recibe respuestas a mensajes viejos acumulados,
uno atrás del otro, en vez de silencio hasta el próximo turno nuevo.

### Causa

`TurnGate.decide()` devuelve `Decision.QUEUE` cuando `self._active is not None`;
`VoiceAgent` entonces encola el turno en `TurnGate._pending` (`gate.enqueue(...)`)
y `_drain()` lo re-emite cuando la voz queda idle (`on_voice_idle` /
`on_voice_status(IDLE)` / `on_audio_output_status` sin PLAYING). `on_interrupt()`
limpiaba `_active`/`_active_prompt` y ponía `_steering = True`, pero **no tocaba
`_pending`**. Secuencia del síntoma: el usuario interrumpe → la voz se calla →
los fragmentos siguientes del usuario generan más `generate` → el primero ejecuta
y los demás se encolan → cuando la voz queda idle, `_drain()` los emite de a uno.

### Solución aplicada (2026-09-18, detalle en `FIX-94.md` sección "FIX-94f")

- `TurnGate.on_interrupt`: si el interrupt viene del **usuario** (reason en
  `{"voice_activity", "user_turn"}`), descarta la cola (`_pending.clear()`) y
  loguea `turn_gate: dropped N queued turn(s) on user interrupt`. Los follow-ups
  entre voces (otro reason/dept) mantienen el comportamiento actual: la cola sobrevive.
- Diagnóstico de cola: al encolar, se loguea
  `turn_gate: queued <event>(<target>) pending=<n>` (el log de `draining` ya existía).
- Sin cambios en las firmas de `enqueue`/`release`/`decide` ni en contratos de eventos.
- Test existente adaptado al nuevo contrato: `test_two_generates_different_voices_queue_second_turn`
  ahora espera 0 llamadas de doktor tras el interrupt de usuario (antes codificaba el bug);
  el drenado de follow-ups no-usuario queda cubierto por regresión nueva.

**Archivos:** `kateto/plugins/system/turn_gate.py`, `kateto/tests/test_turn_gate.py`
