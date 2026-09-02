---
id: 86
title: "ALSA mmap xrun en streams persistentes y demora artificial en cue de objeción"
severity: Crítica
status: resolved
component: kateto/plugins/audio_output/player.py, kateto/plugins/bate_debate/orchestrator.py
resolved: 2026-09-01
---

## 86. ALSA mmap xrun en streams persistentes y demora artificial en cue de objeción

**Severidad:** Crítica
**Componente:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/bate_debate/orchestrator.py`

### Descripción

En el log de ejecución a las `16:12:30`, el TTS estuvo en silencio durante los turnos intermedios y solo se reactivó en el veredicto final de la jueza Jane. En la salida de consola de ALSA aparecieron los siguientes errores:
```text
Expression 'alsa_snd_pcm_mmap_begin( self->pcm, &areas, &self->offset, numFrames )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 3998
Expression 'PaAlsaStreamComponent_RegisterChannels( &self->playback, &self->bufferProcessor, &playbackFrames, &xrun )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 4118
Expression 'PaAlsaStream_SetUpBuffers( stream, &framesGot, &xrun )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 4495
```

### Causa

1. **Inanición de buffers ALSA en streams persistentes:**
   Mantener un `RawOutputStream` abierto indefinidamente entre turnos de debate (mientras los modelos de lenguaje tardan entre 6 y 15 segundos en generar la siguiente respuesta sin alimentar muestras PCM a ALSA) provoca una condición de *buffer underrun / xrun* a nivel de kernel de Linux. Una vez que ALSA falla en `alsa_snd_pcm_mmap_begin`, el descriptor PCM de PortAudio queda permanentemente roto. Debido a que los errores de escritura se silenciaban en `SoundDeviceOutputStream.write()`, el descriptor dañado nunca se cerraba ni se reabría, silenciando todos los turnos subsiguientes hasta que un cambio de formato o reseteo de stream creaba uno nuevo.
2. **Retardo artificial post-evaluación en la objeción:**
   En `orchestrator.py`, la llamada a Ollama para considerar una objeción ya demoraba entre 6 y 8 segundos. Luego, un bucle `while (time.monotonic() - t0) < cue_duration:` añadía otros 8 a 10 segundos adicionales, provocando que la objeción se ejecutara mucho después de que el orador hubiera terminado su argumento.

### Solución aplicada

1. **Cierre limpio por fin de turno y auto-recuperación ante xrun (`player.py`):**
   - Al recibir `data.final = True` o ante una interrupción, `AudioOutputPlayer` ahora invoca `self._close_stream()`, liberando limpiamente el dispositivo ALSA y evitando la inanición de buffers durante las pausas entre turnos.
   - En `SoundDeviceOutputStream.write()`, cualquier excepción de PortAudio (`PortAudioError`) escala hacia arriba.
   - En el bucle de escritura de `on_audio_output`, si se captura un error de escritura, se cierra el stream abortado con `_close_stream(abort=True)` y se reabre instantáneamente un stream nuevo y limpio para continuar reproduciendo sin pérdida de audio.
2. **Optimización del ciclo de objeción (`orchestrator.py`):**
   - Se ajustó el bucle de sincronización para cortar de inmediato si el reproductor ya no está emitiendo (`getattr(player, "_playing", False)`), evitando tiempos muertos artificiales.

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/tests/test_edgetts_interruption.py`
