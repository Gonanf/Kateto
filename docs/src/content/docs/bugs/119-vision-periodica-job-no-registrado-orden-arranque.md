---
id: 119
title: "Visión periódica: el job nunca se registra cuando el plugin se habilita antes que el scheduler"
severity: Alta
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 119. Visión periódica: el job nunca se registra cuando el plugin se habilita antes que el scheduler

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/static_vision_plugin.py`

### Descripción

Reporte textual del usuario: *"El vídeo rag no se está ejecutando de vuelta, lo había configurado
cada 30 segundos y antes funcionaba pero ahora ya no."* La config estaba bien
(`jane.vision_periodic = true` + `jane.vision_interval = "30s"`, sin pisos por voz) y el runtime
tenía `static_vision` y `executor_scheduler` enabled. Pero `GET /plugins` mostraba `static_vision`
(#16) habilitado antes que `executor_scheduler` (#25): el `schedule_request` emitido desde
`StaticVisionPlugin.enable()` no tenía ningún suscriptor todavía y se perdía en silencio.

### Impacto

Carrera de arranque: según el orden de habilitación, el job `vision-describe-<voz>` se registraba
o no (de ahí el "antes funcionaba y ahora no"). Sin job no hay ticks periódicos y la narración
ambiental deja de ejecutarse sin ningún error visible: el plugin logueaba
`[vision] scheduled ...` incondicionalmente al emitir, afirmando un registro que nunca ocurrió.

### Causa

Trap general del bus: `PluginManager.enable_plugin` llama `plugin.enable()` **antes** de registrar
al plugin en `self._plugins` y de suscribir sus handlers (`kateto/core/manager.py:74-92`), y los
plugins se habilitan en serie en el orden de `self._plugins` (`kateto/run_mode.py:139-141`). Todo
evento emitido desde `enable()` no tiene receptores todavía: `manager.emit` lo despacha a cero
receptores (`dispatch ... to []`) y se pierde. `StaticVisionPlugin._schedule_periodic` agregaba el
`job_id` a `_periodic_jobs` al emitir —sin ack— así que nunca reintentaba.

### Solución aplicada

- El ack manda: `static_vision` escucha `schedule_result` (`on_schedule_result`). `_periodic_jobs`
  se agrega **sólo cuando llega el ack**; la línea `[vision] scheduled ...` se movió al ack y en el
  emit no se afirma nada. Un ack con `error` loguea WARNING (`[vision] schedule failed for ...`) y
  no reintenta (un `"already scheduled"` se toma como registrado, sin duplicar).
- Reintento acotado: las voces pendientes (voz → interval) reintentan con backoff
  `(2.0, 5.0, 10.0, 20.0, 30.0, 30.0)` hasta el ack. Al agotarse: un único
  WARNING `[vision] vision-describe-<voz> NOT registered after N attempts
  (is executor_scheduler enabled?)` con el motivo, sin spam.
- Cada reintento reevalúa las voces conocidas (`capabilities includes "voice"`), así que una voz
  que aparece tarde igual consigue su job.
- Sin duplicados: un solo job por voz (mismo `job_id`); `disable()` cancela el job y los reintentos
  pendientes.

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/tests/test_vision_lifecycle.py`
