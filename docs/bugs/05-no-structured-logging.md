---
id: 5
title: "Sin logging estructurado"
severity: Media
status: resolved
component: kateto/voices/base.py, kateto/providers/zonos.py
---

## 5. Sin logging estructurado — ✅ RESUELTO

**Severidad:** Media
**Componente:** `kateto/voices/base.py`, `kateto/providers/zonos.py`

El proyecto usa `print()` para salida de depuración y errores. No hay:
- Logger configurable por módulo
- Niveles (DEBUG, INFO, WARNING, ERROR)
- Formato estructurado (JSON o timestamp + módulo + nivel)
- Manejo de logs para producción

**Impacto:** Dificultad para debuggear issues en producción, especialmente en un sistema multi-agente con eventos asíncronos. No hay trazabilidad de qué eventos se emitieron, qué plugins respondieron, ni dónde falló el pipeline.

**Causa:** El MVP se construyó rápido con Codex, y `print()` es el camino más corto. No se diseñó un sistema de logging desde el inicio.

**Solución aplicada:** Se reemplazaron las escrituras a `/tmp/kateto_voice_debug.txt` con `logging.getLogger(__name__).debug()` en `voices/base.py` y `providers/zonos.py`. Los `print()` en `__main__.py` se mantienen (son apropiados para CLI).

**Fix:** Se reemplazaron las escrituras a `/tmp/kateto_voice_debug.txt` y `/tmp/kateto_tts_*` con llamadas a `logging.getLogger(__name__).debug(...)` en `voices/base.py` y `providers/zonos.py`.

**Archivos:** `kateto/voices/base.py`, `kateto/providers/zonos.py`

**Evidencia:** No hay más escrituras a disco vía `open()` para debug. Los `print()` en `__main__.py` se mantienen (son apropiados para CLI).
