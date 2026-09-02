---
id: 84
title: "Stream de PortAudio permanece inactivo tras stream.abort() silenciando todo audio posterior"
severity: Crítica
status: resolved
component: kateto/plugins/audio_output/player.py
resolved: 2026-09-01
---

## 84. Stream de PortAudio permanece inactivo tras stream.abort() silenciando todo audio posterior

**Severidad:** Crítica
**Componente:** `kateto/plugins/audio_output/player.py`

### Descripción

Al ocurrir una objeción e interrumpirse el orador anterior, todo el audio generado a partir de ese momento (incluyendo la propia objeción y los turnos posteriores) se enmudecía completamente, a pesar de que EdgeTTS generaba y despachaba los paquetes PCM con normalidad en el bus de eventos.

### Causa

En `AudioOutputPlayer`, para silenciar el hardware de audio instantáneamente ante una interrupción sin destruir el descriptor de ALSA/PortAudio, se invocaba `stream.abort()`.
En la API nativa de PortAudio (`sounddevice`), `stream.abort()` detiene y desactiva el stream (`stream.active = False`). 
Posteriormente, cuando llegaban las muestras PCM de la objeción y de los turnos siguientes:
1. `_stream_for()` reutilizaba el stream persistente ya existente, pero **no llamaba a `stream.start()`**.
2. Al ejecutar `stream.write(chunk)` sobre un stream inactivo, PortAudio arrojaba `sounddevice.PortAudioError: Stream is stopped [PaErrorCode -9983]`.
3. `SoundDeviceOutputStream.write()` capturaba silenciosamente la excepción y retornaba `None`.
4. El proceso continuaba sin errores visibles, pero la tarjeta de sonido no reproducía nada.

### Solución aplicada

1. **Propiedad reactiva y verificación en `SoundDeviceOutputStream` (`player.py`):**
   - Se implementó la propiedad `@property def active(self) -> bool` que delega en el estado del stream de `sounddevice`.
   - En `start()`, se añadió verificación `if not self.active: self._stream.start()`.
   - En `write()`, antes de enviar los bytes se verifica `if not self.active: self.start()`, reactivando el stream de inmediato en caso de haber sido abortado o detenido.
2. **Reactivación explícita en `_stream_for()` (`player.py`):**
   - Cuando se reutiliza un stream existente para un nuevo turno de voz, se invoca incondicionalmente `stream.start()` para garantizar que el estado de reproducción esté listo.

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/tests/test_edgetts_interruption.py`
