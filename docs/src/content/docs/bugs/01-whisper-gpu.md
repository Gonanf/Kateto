---
title: "whisper-server: `--device 1` no usa GPU correctamente"
description: "1. whisper-server: `--device 1` no usa GPU correctamente"
severity: Media
status: resolved
component: kateto/providers/whisper.py
resolved: 2026-08-29
---

## 1. whisper-server: `--device 1` no usa GPU correctamente

**Severidad:** Media
**Componente:** `kateto/providers/whisper.py` / servidor whisper.cpp

La flag `--device 1` no seleccionaba la GPU Vulkan correcta si el ejecutable no contaba con soporte nativo de backend Vulkan vinculado a las librerías GGML.

**Impacto:** Inferencia de whisper en CPU (~22.5 segundos para un audio de 10s). Latencia alta en el pipeline de transcripción.

**Causa:** `pywhispercpp` por defecto se compila con backend CPU únicamente. Para aprovechar la GPU discreta (AMD Radeon RX 6500 XT en Vulkan1) se requiere `whisper-server` compilado con `-DGGML_VULKAN=ON` y la flag `-dev 1`.

**Solución aplicada:**
1. En `kateto/providers/whisper.py`: `WhisperServerProcessProvider` auto-detecta la existencia del binario nativo compilado con Vulkan (`whisper-server`) y envía la flag `-dev 1` al arrancar el proceso servidor.
2. En `kateto/tools/compiler.py`: Se configuraron las variables de entorno `-DGGML_VULKAN=on -DWHISPER_VULKAN=on` y `--no-binary pywhispercpp` para recompilaciones desde el CLI.
3. Se verificó en hardware real obteniendo transcripción en 2.2 segundos (10x de aceleración).

**Archivos:** `kateto/providers/whisper.py`, `kateto/tools/compiler.py`, `~/.config/kateto/config.toml`
