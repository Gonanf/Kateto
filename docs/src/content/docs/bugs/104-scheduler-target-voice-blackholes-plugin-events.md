---
id: 104
title: "Scheduler rutea el evento al target_voice y el plugin consumidor jamás lo recibe"
severity: Alta
status: resolved
component: kateto/plugins/executor/scheduler.py
resolved: 2026-09-17
---

## 104. Scheduler rutea el evento al target_voice y el plugin consumidor jamás lo recibe

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/scheduler.py`

### Descripción

Con jobs `vision-describe-<voz>` registrados y disparándose (`fired -> vision_describe_request`), ningún describe se ejecutaba jamás. El log mostraba fires cada 30s pero cero líneas `[vision] describe`.

### Impacto

Toda la narración periódica de visión muerta aunque el scheduling pareciera sano.

### Causa

`SchedulerPlugin._fire` emitía con `target=job.target_voice` (la voz beneficiaria, p. ej. `conquest`). El bus solo entrega a ese plugin, y la voz no maneja `vision_describe_request` — el verdadero consumidor (`static_vision`) quedaba excluido. `target_voice` solo debía gobernar el deferral (no describir mientras la voz habla), no el delivery.

### Solución aplicada

En `_fire`: si el target no está entre los receivers registrados del evento, fallback a broadcast (los targets que SÍ manejan el evento, p. ej. voces para `generate`, no cambian; el `target_voice` aleatorio documentado tampoco).

**Regresión:** `test_periodic_talking_state_defers_tick` ahora aserta broadcast + respuesta del plugin de visión.

**Archivos:** `kateto/plugins/executor/scheduler.py`, `kateto/tests/test_vision_lifecycle.py`
