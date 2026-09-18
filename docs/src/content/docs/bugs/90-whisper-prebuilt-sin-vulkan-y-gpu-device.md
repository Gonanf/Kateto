---
id: 90
title: "Wheel prebuilt de pywhispercpp sin Vulkan: inferencia CPU de 125s y sin selección de GPU"
severity: Alta
status: resolved
component: kateto/providers/whisper.py, kateto/core/config.py, kateto/tools/compiler.py
resolved: 2026-09-17
---

## 90. Wheel prebuilt de pywhispercpp sin Vulkan: inferencia CPU de 125s y sin selección de GPU

**Severidad:** Alta
**Componente:** `kateto/providers/whisper.py`, `kateto/core/config.py`, `kateto/tools/compiler.py`

### Descripción

Instalado vía `uv tool install kateto[whispercpp]`, Whisper transcribía 3s de audio en ~125s. El log mostraba `whisper_backend_init_gpu: no GPU found` aunque `compiler.whisper.backend = "vulkan"`. Además no existía forma de elegir entre múltiples GPUs (AMD RX 6500 XT vs Intel Iris Xe).

### Impacto

Latencia de 2+ minutos por turno de voz; imposible usar aceleración aunque el hardware la soporta.

### Causa

1. El wheel prebuilt de `pywhispercpp` se compila sin backend Vulkan.
2. `PyWhisperCppProvider` construía `Model(nombre, n_threads)` sin pasar `context_params`, así que whisper.cpp usaba siempre `gpu_device = 0` aunque `pywhispercpp` sí soporta la clave `gpu_device` en `context_params`.

### Solución aplicada

- Recompilar con `kateto compile whisper --backend vulkan` (ver bug 91 por los fallos de compilación).
- Nuevo knob `gpu_device`: `PluginSettings.gpu_device` + resolución en `PyWhisperCppProvider` con precedencia arg explícito > `gpu_device` > `device` numérico (compartido con el backend `server`), pasado como `context_params={"gpu_device": N}`. Verificado en runtime: `gpu_device = 1`, `using Vulkan1 backend`, modelo de 573MB en la Iris Xe, inferencia de 4.5s en ~6.2s.
- Comentario de ejemplo en `config/defaults/config.toml`.

**Archivos:** `kateto/providers/whisper.py`, `kateto/core/config.py`, `kateto/tools/compiler.py`, `config/defaults/config.toml`, `kateto/tests/test_whisper_provider.py`
