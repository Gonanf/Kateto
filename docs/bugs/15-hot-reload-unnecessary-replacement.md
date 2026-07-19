---
id: 15
title: "Hot reload reemplaza todos los plugins sin verificar si cambiaron"
severity: Crítica
status: resolved
component: kateto/core/hot_reload.py (_refresh_discovered)
---

## 15. Hot reload reemplaza todos los plugins sin verificar si cambiaron — ✅ RESUELTO

**Severidad:** Crítica
**Componente:** `kateto/core/hot_reload.py` (`_refresh_discovered`)

`_refresh_discovered` reemplazaba TODOS los plugins al ejecutar discovery, sin verificar si la definición de la clase cambió. Esto cancelaba workers activos (incluyendo llamadas LLM en curso) y destruye estado de plugins que no cambiaron.

**Fix:** Se agregó `type(replacement) is not type(active)` antes de `replace_plugin`. Solo se reemplaza si la clase del plugin cambió (módulo recargado con nueva definición).

```python
# Antes (bug):
await self.manager.replace_plugin(active, replacement)  # SIEMPRE

# Después (fix):
elif type(replacement) is not type(active):
    await self.manager.replace_plugin(active, replacement)  # solo si la clase cambió
```

**Archivos:** `kateto/core/hot_reload.py`, `kateto/tests/test_hot_reload_discovery.py`, `kateto/tests/test_hot_reload_no_unnecessary_replacement.py` (nuevo)

**Evidencia:** 9/9 tests pasan. Test `test_hot_reload_does_not_replace_unchanged_plugins` verifica que plugins sin cambios no son reemplazados.
