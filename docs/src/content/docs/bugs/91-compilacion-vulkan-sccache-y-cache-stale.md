---
id: 91
title: "Compilación Vulkan falla por sccache roto y por caché cmake stale de uv"
severity: Media
status: open
component: kateto/tools/compiler.py
---

## 91. Compilación Vulkan falla por sccache roto y por caché cmake stale de uv

**Severidad:** Media
**Componente:** `kateto/tools/compiler.py`

### Descripción

`kateto compile whisper --backend vulkan` falló dos veces con errores distintos:

1. `sccache: Permission denied (os error 13)` al hashear `ggml.c` — el build autodetectaba un sccache con caché inaccesible y moría.
2. Tras el reintento, CMake reutilizó el directorio de build cacheado por uv (`~/.cache/uv/sdists-v9/...`) que apuntaba a `ninja` de un entorno efímero ya borrado (`builds-v0/.tmpEmCka5/bin/ninja: no such file or directory`).

### Impacto

Sin compilar no hay backend Vulkan (ver bug 90).

### Causa

1. whisper.cpp activa sccache si lo encuentra en PATH, sin verificar que funcione.
2. uv reutiliza el `src/build` del sdist entre reintentos, conservando un `CMakeCache` con rutas muertas.

### Posible solución

1. ✅ Aplicado: `get_env_for_backend` exporta `GGML_CCACHE=OFF` (el switch que el propio whisper.cpp documenta) y vacía `CMAKE_C_COMPILER_LAUNCHER`/`CMAKE_CXX_COMPILER_LAUNCHER`.
2. Workaround manual para la caché stale: `uv cache clean pywhispercpp` y reintentar. Pendiente una mitigación en `compile_whisper` (p. ej. detectar el fallo o limpiar la caché del sdist automáticamente).

**Archivos:** `kateto/tools/compiler.py`, `kateto/tests/test_compiler.py`
