---
id: 85
title: "Fuga de bandera _playing en EdgeTTS causando congelamiento de 45s en wait_idle"
severity: Crítica
status: resolved
component: kateto/plugins/audio_output/edgetts.py, kateto/plugins/bate_debate/orchestrator.py
resolved: 2026-09-01
---

## 85. Fuga de bandera _playing en EdgeTTS causando congelamiento de 45s en wait_idle

**Severidad:** Crítica
**Componente:** `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`

### Descripción

Durante el debate, cada turno posterior a una objeción o síntesis quedaba congelado exactamente durante 44-45 segundos (evidenciado en `log.txt` entre `16:09:35` y `16:10:19`), provocando silencios intolerables entre turnos.

### Causa

1. **Falta de reset de `_set_playing(False)` en `EdgeTTSAudioOutput._emit_pcm`:**
   En `kateto/plugins/audio_output/edgetts.py`, `_emit_pcm` comenzaba con `await self._set_playing(True)`. Sin embargo, al finalizar la iteración de streaming y emitir las muestras finales, nunca se llamaba a `_set_playing(False)`.
   Como consecuencia:
   - `self._playing` quedaba en `True` de forma permanente.
   - La propiedad `is_busy` del plugin siempre retornaba `True`:
     ```python
     if self._playing:
         return True
     ```
   - Cada llamada a `tts_plugin.wait_idle(timeout=45.0)` en `orchestrator.py` se quedaba esperando los 45 segundos íntegros antes de retornar por expiración de timeout.
2. **Timeout estático desproporcionado en el orquestador:**
   `_wait_for_speech_finish` utilizaba un timeout estático de 45 segundos para cualquier intervención independientemente de su longitud, convirtiendo cualquier anomalía en una pausa de casi un minuto.

### Solución aplicada

1. **Garantía `try ... finally` en `_emit_pcm` (`edgetts.py`):**
   Se envolvió la totalidad del proceso de streaming y emisión de audio en un bloque `try ... finally` que asegura incondicionalmente la ejecución de:
   ```python
   finally:
       await self._set_playing(False)
       if not self.is_busy:
           self._idle_event.set()
   ```
   Esto permite que `wait_idle()` se libere en 0 milisegundos en cuanto termina de sintetizar el texto.
2. **Escalado dinámico del timeout de espera (`orchestrator.py`):**
   El timeout de `wait_idle()` ahora se calcula proporcionalmente al número de palabras del turno:
   `idle_timeout = max(4.0, min(25.0, est_duration * 1.5))`, evitando estancamientos largos en caso de imprevistos.

**Archivos:** `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`
