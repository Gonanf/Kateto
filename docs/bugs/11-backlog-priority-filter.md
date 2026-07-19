---
id: 11
title: "backlog_list no soporta filtro por prioridad"
severity: Baja
status: resolved
component: kateto/core/event.py (BacklogListData)
---

## 11. backlog_list no soporta filtro por prioridad — ✅ RESUELTO

**Severidad:** Baja
**Componente:** `kateto/core/event.py` (BacklogListData)

`BacklogListData` solo tiene filtro por `status` (BacklogStatus) y `priority` (BacklogPriority), pero el filtro `status` no acepta valores de prioridad. Si se pasa `"Must"` a `status`, falla con error de validación.

**Evidencia:**
```
BacklogListData(status="Must") -> ValidationError
  Input should be an instance of BacklogStatus [type=is_instance_of, input_value=<BacklogPriority.MUST: 'Must'>]
```

**Causa:** `BacklogListData.status` solo aceptaba `BacklogStatus`. El validator devolvía `BacklogPriority` pero el type hint del campo lo rechazaba.

**Impacto:** Los usuarios no pueden filtrar backlog por prioridad desde el LLM sin usar el campo correcto.

**Solución aplicada:** `BacklogListData.status` ahora acepta `BacklogStatus | BacklogPriority | None`. `BacklogListData(status="Must")` funciona sin error de validación.

**Fix:** `BacklogListData.status` ahora acepta `BacklogStatus | BacklogPriority | None` en vez de solo `BacklogStatus`. Esto permite pasar `status="Must"` (BacklogPriority) como filtro sin error de validación.

**Archivos:** `kateto/core/event.py`

**Evidencia:** `BacklogListData(status="Must")` ya no lanza `ValidationError`. El campo `priority` sigue funcionando igual.
