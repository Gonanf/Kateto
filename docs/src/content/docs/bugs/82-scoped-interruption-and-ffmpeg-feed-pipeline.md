---
id: 82
title: "Interrupción de voz global mutando al siguiente orador y deadlock en feed de FFmpeg"
severity: Alta
status: resolved
component: kateto/plugins/audio_output/edgetts.py, kateto/providers/edgetts.py, kateto/plugins/bate_debate/orchestrator.py
resolved: 2026-09-01
---

## 82. Interrupción de voz global mutando al siguiente orador y deadlock en feed de FFmpeg

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_output/edgetts.py`, `kateto/providers/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`

### Descripción

Tras el turno de argumento de Whisperer a las `15:41:39`, la siguiente intervención (la objeción levantada contra Doktor a las `15:42:46`) enmudeció por completo. Durante 45 segundos no hubo sonido ni eventos de audio, hasta que expiró el timeout de `wait_idle(timeout=45.0)`.

### Causa

1. **Estado `_interrupted` global en vez de por voz:**
   Al emitirse el evento `interrupt` para cortar a Doktor, `EdgeTTSAudioOutput.on_interrupt` activaba `self._interrupted = True`. En `_emit_pcm`, la condición `if not raw_text or self._interrupted: return` evaluaba a `True` para **cualquier voz**, abortando el turno de la objeción del nuevo orador (Whisperer) de inmediato y sin emitir audio ni `final=True`.
2. **Descarte indiscriminado de cola en `on_interrupt`:**
   El bucle de vaciado de cola `while not self.queue.empty(): self.queue.get_nowait()` purgaba cualquier evento `text_chunk` que ya hubiera entrado en cola para el siguiente orador si coincidía en la misma ráfaga de tiempo.
3. **Deadlock potencial en `_feed` de `EdgeTTSProvider`:**
   En `providers/edgetts.py`, si `communicate.stream()` arrojaba un error o cerraba abruptamente, `stdin.close()` nunca se ejecutaba en `_feed()`. Como resultado, `ffmpeg` no recibía EOF y `stdout.read()` se bloqueaba indefinidamente.

### Solución aplicada

1. **Alcance acotado de interrupción por voz (`edgetts.py`):**
   - En `_emit_pcm`, la condición de descarte se restringió a la voz activa interrumpida:
     `if self._interrupted and data.voice_id == self._interrupted_voice: return`.
   - Si llega un `TextChunk` con `sequence == 0` o de una voz diferente, `self._interrupted` se restablece automáticamente.
   - En `on_interrupt`, la purga de la cola descarta exclusivamente los paquetes de `_interrupted_voice`, preservando los mensajes entrantes de otros oradores.
2. **Garantía de cierre de `stdin` en `providers/edgetts.py`:**
   - Se envolvió la iteración de streaming de Microsoft Edge TTS en un bloque `try ... finally` que asegura el cierre (`stdin.close()`) de la tubería de entrada de `ffmpeg` ante cualquier excepción o fin prematuro.
3. **Pausa de estabilización entre interrupción y objeción (`orchestrator.py`):**
   - Se añadió un respiro de 80ms (`await asyncio.sleep(0.08)`) tras el `interrupt` antes de emitir la objeción, garantizando que todos los plugins hayan vaciado buffers antes de procesar el nuevo audio.

**Archivos:** `kateto/plugins/audio_output/edgetts.py`, `kateto/providers/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`
