---
id: 81
title: "PortAudio ALSA assertion crash, stream persistence and debate turn pacing"
severity: Alta
status: resolved
component: kateto/plugins/audio_output/player.py, kateto/plugins/audio_output/edgetts.py, kateto/plugins/bate_debate/orchestrator.py
resolved: 2026-09-01
---

## 81. PortAudio ALSA assertion crash, stream persistence and debate turn pacing

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/cli/commands.py`

### Descripción

1. Tras la primera interrupción u objeción en el debate, las voces de TTS dejaban de sonar por un periodo de tiempo y posteriormente todos los discursos acumulados se reproducían simultáneamente en cascada.
2. En los logs se producía un fallo de aserción en el driver ALSA de PortAudio:
   `Expression 'res' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 3506`
   `python3: src/hostapi/alsa/pa_linux_alsa.c:4174: PaAlsaStream_SetUpBuffers: Assertion self->neverDropInput failed.`
3. El orador era interrumpido demasiado pronto (al término de la primera oración, en ~18 palabras) en lugar de alcanzar a pronunciar la mayor parte de su premisa (~70% del argumento, ~35-40 palabras).
4. Existía un retraso excesivo y hardcodeado de 3.5 segundos entre la intervención del juez y el inicio de los turnos de los debatientes.

### Causa

1. **Regresión de cierre de stream en `AudioOutputPlayer`:**
   Al recibir `data.final`, el reproductor cerraba el stream de PortAudio (`self._close_stream()`), destruyendo y recreando el descriptor ALSA para cada frase. Al coexistir con la captura continua de micrófono (`RawInputStream` con `neverDropInput=1`), ALSA invalidaba los buffers y fallaba la aserción en C, bloqueando la salida de audio hasta que se liberaba en bloque.
2. **Chunk size de 4KB inundando el bus:**
   EdgeTTS emitía bloques de 4096 bytes (~85ms de audio) generando hasta 50 eventos por segundo en el bus de eventos, congestionando la cola del reproductor.
3. **Punto de corte rígido en `target_words = 18`:**
   En argumentos de 50 palabras, cortar en la palabra 18 truncaba la primera oración sin permitir desarrollar la tesis antes de la objeción.
4. **`arg_delay` configurado en 3.5 segundos por defecto:**
   En `commands.py`, el retardo entre turnos (`delay_between_arguments`) forzaba un `sleep(3.5)` adicional a pesar de que `wait_idle()` ya garantizaba la sincronización del fin de voz.

### Solución aplicada

1. **Persistencia del stream en `AudioOutputPlayer` (`player.py`):**
   - Se eliminó el cierre de stream en `data.final`. El stream de salida de PortAudio se mantiene abierto y reutilizable entre frases, cerrándose únicamente al deshabilitar el plugin.
   - En caso de interrupción, se invoca `stream.abort()` para limpiar los buffers de hardware en 0ms sin destruir el manejador de PortAudio.
2. **Ventana de streaming de 16KB en `EdgeTTSAudioOutput` (`edgetts.py`):**
   - Se introdujo un umbral de 16.384 bytes (~340ms). El audio arranca de inmediato (<350ms) pero emite 3 eventos/s en vez de 50, garantizando estabilidad en el bus.
3. **Corte de objeción al ~70% del argumento (`orchestrator.py`):**
   - `_find_interruption_cue` ahora calcula el corte en torno al 70% de la longitud total (`target_ratio=0.70`), buscando un límite natural de cláusula o puntuación. El orador pronuncia ~35-40 palabras antes de que entre la objeción con `"—"`.
4. **Pausa natural de 0.5s en debates (`commands.py`):**
   - Se redujo el retardo por defecto entre turnos a 0.5 segundos, eliminando la pausa artificial tras el dictamen del juez.

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/cli/commands.py`
