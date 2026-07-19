---
id: 6
title: "Hot-reload sin test coverage"
severity: Media
status: resolved
component: kateto/core/hot_reload.py, kateto/tests/
---

## 6. Hot-reload sin test coverage — ✅ RESUELTO

**Severidad:** Media
**Componente:** `kateto/core/hot_reload.py`, `kateto/tests/`

El sistema de hot-reload (`HotReloadController`) es una pieza crítica: permite reemplazar plugins en caliente mientras el bus de eventos sigue corriendo. Sin embargo:

- **No tiene tests unitarios**
- **No tiene tests de integración** (reemplazar un plugin y verificar que los eventos se sigan emitiendo)
- Cualquier cambio en `manager.py` o `plugin.py` puede romper hot-reload sin que los tests lo detecten

**Impacto:** El TUI con hot-reload (feature clave del MVP) puede romperse silenciosamente. Regresiones en hot-reload no se detectan hasta ejecución manual.

**Causa:** hot-reload se agregó tarde en el desarrollo como feature de polish. Los tests existentes se escribieron antes.

**Solución aplicada:** Se agregaron 3 tests unitarios que cubren:
1. Reemplazo de plugin via `ReplacementFactory`
2. Observers se mantienen después del reemplazo
3. Eventos llegan al plugin reemplazado

Tests: `test_hot_reload_replaces_plugin_via_replacement_factory`, `test_hot_reload_preserves_observers_after_replacement`, `test_hot_reload_replaced_plugin_receives_events`

**Fix:** Se agregaron 3 tests unitarios nuevos en `test_hot_reload_discovery.py`:

| Test | Verifica |
|------|----------|
| `test_hot_reload_replaces_plugin_via_replacement_factory` | Reemplazo de plugin via `ReplacementFactory` |
| `test_hot_reload_preserves_observers_after_replacement` | Observers se mantienen después del reemplazo |
| `test_hot_reload_replaced_plugin_receives_events` | Eventos llegan al plugin reemplazado |

**Archivos:** `kateto/tests/test_hot_reload_discovery.py`

**Evidencia:** Los 5 tests (2 existentes + 3 nuevos) pasan:
```
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_replaces_plugin_via_replacement_factory PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_preserves_observers_after_replacement PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_replaced_plugin_receives_events PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_accepts_repository_plugin_and_voice_roots PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_reconciles_created_modified_and_deleted_definitions PASSED
```
