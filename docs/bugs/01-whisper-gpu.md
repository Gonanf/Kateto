---
id: 1
title: "whisper-server: `--device 1` no usa GPU correctamente"
severity: Media
status: open
component: providers/whisper.py / servidor whisper.cpp externo
---

## 1. whisper-server: `--device 1` no usa GPU correctamente

**Severidad:** Media
**Componente:** `providers/whisper.py` / servidor whisper.cpp externo

La flag `--device 1` no selecciona la GPU Vulkan correcta. En sistemas con múltiples GPUs (p.ej. Intel Iris Xe + AMD Radeon RX 6500 XT), whisper.cpp ignora el device index y usa la GPU por defecto o cae a CPU.

**Impacto:** Inferencia de whisper en CPU (~1.4 t/s) en vez de GPU. Latencia alta en el pipeline de transcripción.

**Causa:** bug conocido en whisper.cpp donde el device index no se mapea correctamente al backend Vulkan cuando hay GPUs integrada + discreta.

**Posible solución:** Forzar device mediante variable de entorno `GGML_VULKAN_DEVICE=1` o configurar `--no-gpu` y usar CPU con más threads. En producción, considerar migrar a un solo dispositivo GPU.
