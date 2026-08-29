---
id: 63
title: "PortAudio ALSA xrun y crash por aserción self->neverDropInput al abrir y cerrar streams concurrentes"
severity: Alta
status: resolved
component: kateto/plugins/audio_output/player.py, kateto/plugins/audio_input/capture.py
resolved: 2026-08-29
---

## 63. PortAudio ALSA xrun y crash por aserción self->neverDropInput al abrir y cerrar streams concurrentes

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_input/capture.py`

### Descripción

Durante la captura continua del micrófono con Silero VAD, la reproducción rápida de frases consecutivas a través de `AudioOutputPlayer` causaba warnings de PortAudio ALSA (`Expression 'res' failed in 'src/hostapi/alsa/pa_linux_alsa.c'`) y finalmente un crash fatal del intérprete de Python:
`python3: src/hostapi/alsa/pa_linux_alsa.c:4174: PaAlsaStream_SetUpBuffers: Assertion self->neverDropInput failed.`

### Impacto

- Cierre abrupto del proceso Kateto durante la interacción por voz.
- Interrupciones en el audio y pérdida de buffer de micrófono.

### Causa

El stream de entrada (`RawInputStream`) corre con `neverDropInput=1` en el driver ALSA. `AudioOutputPlayer` abría y destruía el stream de salida (`RawOutputStream`) entre cada frase emitida por el sintetizador. Al reabrir y recalcular buffers en el dispositivo ALSA compartido mientras el stream de entrada estaba activo, la capa C de PortAudio invalidaba los buffers internos disparando la aserción.

**Solución aplicada:**

1. En `AudioOutputPlayer`: Se mantuvo el stream de salida (`RawOutputStream`) abierto y persistente en memoria tras su primera inicialización, eliminando el cierre prematuro entre frases en `_run_mixer`. El stream se cierra únicamente cuando el plugin es deshabilitado explícitamente (`disable()`).
2. Se configuró `latency="high"` y tamaños de bloque generosos (`blocksize=2048` para salida, `blocksize=1024` para entrada) garantizando holgura en los buffers DMA de ALSA para evitar xruns.

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_input/capture.py`
