---
id: 80
title: "EdgeTTS chunked PCM streaming and implanted objection cue interruption"
severity: Media
status: resolved
component: kateto/plugins/audio_output/edgetts.py
resolved: 2026-09-01
---

## 80. EdgeTTS chunked PCM streaming and implanted objection cue interruption

**Severidad:** Media
**Componente:** `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`

### Descripción

1. EdgeTTS presentaba un retraso de inicio de 10 a 12 segundos antes de comenzar a emitir sonido para oraciones largas en debates.
2. Durante las objeciones, el orador era interrumpido bruscamente tras pocas palabras (ej. *"Yo defiendo que es ético—"*) en lugar de entregar su premisa o cláusula inicial hasta el punto natural de contienda con guión (`"—"`).

### Causa

1. **Acumulación forzada en buffer en vez de streaming:**
   En `EdgeTTSAudioOutput._emit_pcm`, a pesar de que el proveedor `stream_sentence()` decodificaba y entregaba bloques de 4KB por streaming, el plugin acumulaba todos los bloques en `pcm_buffer = bytearray()` hasta que llegaba `output.final`. No se emitía una sola muestra a `AudioOutputPlayer` hasta que Microsoft terminaba de descargar todo el archivo MP3.
2. **Corte ciego por tiempo de reloj:**
   En `orchestrator.py`, la objeción calculaba un tiempo con `asyncio.sleep()` relativo al reloj de Python desde la generación del LLM (mientras EdgeTTS aún descargaba el audio). Al comenzar a sonar el audio, el sleep ya había expirado y la objeción silenciaba la voz a los 2 segundos de reproducción.

### Solución aplicada

1. **Streaming inmediato en `EdgeTTSAudioOutput` (`kateto/plugins/audio_output/edgetts.py`):**
   - Se eliminó la acumulación en `pcm_buffer`. Cada chunk de 4KB decodificado por ffmpeg se emite inmediatamente al bus de eventos hacia `AudioOutputPlayer`, comenzando la reproducción en altavoces en ~250-350ms.
2. **Doble modalidad de interrupción (Inmediata vs. Cue Implantado):**
   - **Modo Inmediato ("Interrupt Now"):** Se mantiene activo para eventos de usuario y VAD cortando el hardware en 0ms.
   - **Modo Cue Implantado (`_find_interruption_cue` en `orchestrator.py`):** Para objeciones en debates, se detecta el límite de cláusula o puntuación natural (~18 palabras). El orador pronuncia su premisa completa hasta el punto de corte (`"—"`), tras lo cual se corta el resto del audio y el oponente irrumpe con la objeción de manera fluida y coherente.

**Archivos:** `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/tests/test_bate_debate.py`
