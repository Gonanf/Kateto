---
id: 92
title: "`kateto compile` instala en el venv del repo pero el runtime usa el entorno de `uv tool`"
severity: Alta
status: open
component: kateto/tools/compiler.py, docs
---

## 92. `kateto compile` instala en el venv del repo pero el runtime usa el entorno de `uv tool`

**Severidad:** Alta
**Componente:** `kateto/tools/compiler.py`, docs

### Descripción

Tras compilar Vulkan con éxito, el runtime seguía reportando `no GPU found`. Inspección: `libggml-vulkan.so` existía en `/home/study/Kateto/.venv/...` pero no en `~/.local/share/uv/tools/kateto/...`. El `kateto compile` se había ejecutado con el código del repo (`uv run kateto`, instalando en el venv del repo) mientras que el `kateto run` diario usaba el shim de `uv tool install` (entorno aislado distinto, con el wheel CPU-only).

### Impacto

Mejoras compiladas (Vulkan, knobs nuevos como `gpu_device`) no tienen efecto hasta que ambos comandos corran en el mismo entorno. Muy confuso porque no hay error visible: simplemente "la GPU no se usa".

### Causa

`_run_installer` invoca `uv pip install` en el entorno activo sin verificar cuál es, y nada advierte la divergencia entre entorno de compilación y de ejecución.

### Posible solución

1. Documentar el flujo soportado: compilar y correr siempre desde el repo (`uv run kateto compile ...` + `uv run kateto run`), o reinstalar la tool desde el repo tras compilar.
2. Que `kateto compile` imprima el `sys.prefix` destino y que el arranque de whisper registre de qué `.so`/entorno cargó el backend (p. ej. presencia de `libggml-vulkan`), para detectar el desajuste en el log en vez de a ciegas.

**Archivos:** `kateto/tools/compiler.py`
