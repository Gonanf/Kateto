---
id: 101
title: "Whisper en Iris Xe vía Vulkan: primera inferencia lenta y rendimiento menor al esperado"
severity: Media
status: open
component: kateto/providers/whisper.py
---

## 101. Whisper en Iris Xe vía Vulkan: primera inferencia lenta y rendimiento menor al esperado

**Severidad:** Media
**Componente:** `kateto/providers/whisper.py`

### Descripción

Con el backend Vulkan funcionando en la Intel Iris Xe (`using Vulkan1 backend`, bug 90), se observó una inferencia de ~60s frente a ~6s habituales para enunciados cortos con `large-v3-turbo-q5_0`.

### Impacto

Latencia esporádica alta aun con GPU.

### Causa

Sospechas, en orden: (1) warmup de compilación de shaders en la primera inferencia tras arrancar (ggml-vulkan crea pipelines lazily; el aviso `Async execution disabled on certain Intel devices` sugiere un path poco optimizado en esta iGPU); (2) enunciado mucho más largo de lo habitual (ver línea `[mic] Captured utterance`); (3) contención de la iGPU con otro proceso (p. ej. Ollama). Sin confirmar cuál.

### Posible solución

1. Comparar primera vs siguientes inferencias tras un arranque para aislar el warmup.
2. Si la velocidad sostenida no alcanza, probar `gpu_device = 0` (AMD RX 6500 XT discreta, mucho más rápida para Whisper) o bajar `audio_processor_whisper.model` a `small`/`base`.
3. Registrar duración del enunciado junto a `Inference time` para normalizar (tiempo por segundo de audio).

**Archivos:** `kateto/providers/whisper.py`
