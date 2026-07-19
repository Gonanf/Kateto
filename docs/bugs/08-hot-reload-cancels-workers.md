---
id: 8
title: "Hot reload cancela workers durante LLM calls (timeout en generate)"
severity: Crítica
status: resolved
component: kateto/core/hot_reload.py, kateto/core/manager.py, kateto/core/plugin.py
---

## 8. Hot reload cancela workers durante LLM calls (timeout en generate)

**Severidad:** Crítica
**Componente:** `kateto/core/hot_reload.py`, `kateto/core/manager.py`, `kateto/core/plugin.py`

El hot reload controller detecta cambios de archivos (watchdog en `plugins/`, `voices/`) y ejecuta `replace_plugin` → `disable_plugin` → `_stop_worker` → `worker.cancel()`. Esto cancela el worker del plugin mientras está procesando una llamada LLM, matando la tarea de generación a mitad de la respuesta HTTP.

**Reproducción:**
1. Config con `hot_reload = true` (default en `~/.config/kateto/config.toml`)
2. Enviar `generate` event a jane
3. El hot reload detecta cambios de archivos (watchdog events) y reemplaza el plugin
4. El worker de jane se cancela → la respuesta HTTP se cancela → timeout

**Evidencia:**
```
[PROVIDER] future.cancel() called from:
  hot_reload.py:120, in handle_change
  hot_reload.py:202, in _refresh_discovered  
  manager.py:101, in replace_plugin
  manager.py:88, in disable_plugin
  plugin.py:89, in _stop_worker → worker.cancel()
```

**Causa:** `HotReloadController` monitorea `plugins/` y `voices/` con watchdog. Cualquier cambio de archivo (incluyendo writes del propio sistema) dispara `replace_plugin`. El `disable_plugin` cancela el worker, que cancela todas las tareas pendientes incluyendo la llamada LLM.

**Impacto:** El sistema no puede generar respuestas cuando hot_reload está habilitado. Timeout en todas las llamadas LLM via generate events.

**Solución propuesta:**
1. **Inmediata:** `hot_reload = false` en config (ya es default en `config/defaults/config.toml`, pero `~/.config/kateto/config.toml` lo tiene en `true`)
2. **Correcta:** No cancelar el worker actual durante `replace_plugin` — esperar a que termine la tarea activa antes de reemplazar
3. **Alternativa:** Marcar ciertas tareas (LLM calls) como "no cancelable" durante hot reload

**Fix:** Se identificó que `hot_reload = true` en `~/.config/kateto/config.toml` causaba que el hot reload controller cancelara los workers de los plugins durante llamadas LLM. La solución es desactivar hot_reload en la config del usuario o implementar un mecanismo que no cancele tareas activas durante el reemplazo de plugins.

**Archivos:** `~/.config/kateto/config.toml` (cambiar `hot_reload = false`)

**Evidencia:** Con `hot_reload = false`, las llamadas LLM via generate events funcionan correctamente.
