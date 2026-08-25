---
id: 61
title: "SchedulerPlugin nunca se ensambla en el runtime y dispara payloads dict que el bus rechaza"
severity: Alta
status: resolved
component: kateto/plugins/executor/__init__.py, kateto/plugins/executor/scheduler.py
resolved: 2026-08-25
---

## 61. SchedulerPlugin nunca se ensambla en el runtime y dispara payloads dict que el bus rechaza

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/__init__.py`, `kateto/plugins/executor/scheduler.py`

### Descripción

`SchedulerPlugin` (commit fa2a185, feature F1) define la maquinaria de autonomía:
jobs one-shot/interval/cron con jitter, horas activas y guardas de voz. Pero:

1. **Ninguna fábrica de discovery lo instancia.** `create_plugins()` de
   `kateto/plugins/executor/` devuelve Classifier/WorkflowRouter/Interrupt/TodoList
   y nada más — el scheduler quedó huérfano. En runtime real, la tool
   `schedule_event` de las voces emite `schedule_request` al vacío y responde
   `{"status": "scheduled"}` aunque nadie agendó nada. El modo autónomo
   ("dispará un standup en 5 minutos") no existe de hecho.
2. **Al disparar, `_fire()` emitía `dict(job.data)` crudo**, pero
   `PluginManager.emit()` exige payloads Pydantic (`event payload must be a
   Pydantic model`). La excepción mataba el loop `_tick()` silenciosamente
   ("Task exception was never retrieved"), dejando jobs trabados para siempre.

### Impacto

- Autonomía rota: voces "agendan" eventos que jamás ocurren.
- `ProcessAudioWhisperPlugin` (transcripción por proceso) depende del scheduler
  para su trigger intervalar — sin scheduler ese plugin tampoco funciona.
- El crash del tick loop era invisible: sin log ni evento de error.

### Causa

El plugin se construyó como pieza aislada (F1 del plan prometheus) y nunca se
conectó al ensamblado; además se probó solo con contratos ya validados, nunca
por el camino real dict→emit.

**Solución aplicada:**

1. `create_plugins()` de executor ahora incluye `SchedulerPlugin()` (always-on,
   desactivable vía `[plugin.executor_scheduler] enabled = false`).
2. `_fire()` coerciona el payload: usa el contrato registrado
   (`manager.get_event_contract`) o cae a `_GenericPayload(values=...)`.
3. e2e nuevo `kateto/tests/test_autonomy_e2e.py`: agenda real via tool →
   verificación de `schedule_result` → disparo → llegada del evento al target.

**Archivos:** `kateto/plugins/executor/__init__.py`, `kateto/plugins/executor/scheduler.py`, `kateto/tests/test_autonomy_e2e.py`
