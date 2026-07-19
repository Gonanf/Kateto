---
id: 4
title: "Plugins sin isolation de errores (sin circuit breaker)"
severity: Alta
status: resolved
component: kateto/core/manager.py / kateto/core/plugin.py
---

## 4. Plugins sin isolation de errores (sin circuit breaker) — ✅ RESUELTO

**Severidad:** Alta
**Componente:** `kateto/core/manager.py` / `kateto/core/plugin.py`

Cuando un handler de evento lanza una excepción, el error se propaga al `emit()` y puede cancelar otros handlers en el mismo dispatch. No hay:
- Mecanismo de circuit breaker
- Aislamiento de failures por plugin
- Estado degradado (un plugin falla, los otros siguen)

**Impacto:** Un solo plugin buggy puede tumbar el event bus completo o silenciar errores. El sistema no tiene manera de "desconectar" un plugin que falla repetidamente.

**Causa:** El dispatch de eventos en `manager.py` usa `gather()` o tareas concurrentes sin manejo granular de errores por handler. El MVP priorizó simplicidad sobre resiliencia.

**Solución aplicada:**
1. Cada handler en `_run()` se ejecuta en try/except individual (ya existía desde el MVP)
2. `_consecutive_failures` se resetea a 0 en éxito, se incrementa en error
3. Al llegar a 5 fallos consecutivos, `_auto_disable_plugin()` deshabilita el plugin y emite `PluginErrorData` con `error_type="TooManyFailures"`
4. Fallos aislados (< 5) siguen reportándose normalmente

**Fix:**
1. `Plugin._run()` ahora resetea `_consecutive_failures = 0` en cada handler exitoso
2. En caso de excepción, incrementa `_consecutive_failures`
3. Si llega a 5 fallos consecutivos, llama a `manager._auto_disable_plugin()` que deshabilita el plugin y emite un evento `error` con `error_type="TooManyFailures"`
4. Fallos aislados (< 5) siguen reportándose como `PluginErrorData`

**Archivos:** `kateto/core/plugin.py`, `kateto/core/manager.py`

**Evidencia:** Tests existentes (`test_plugin_manager.py`) siguen pasando. El mecanismo no interfiere con handlers que funcionan correctamente.
