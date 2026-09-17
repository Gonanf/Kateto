---
id: 88
title: "Mixer task dies on PortAudio host error -9999 (unretrieved exception, audio silent)"
severity: Alta
status: resolved
component: kateto/plugins/audio_output/player.py
resolved: 2026-09-06
---

## 88. Mixer task dies on PortAudio host error -9999

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_output/player.py`

### Descripción

Durante reproducción por el mixer (`_run_mixer`), `stream.write` lanzó
`sounddevice.PortAudioError: Unanticipated host error [PaErrorCode -9999]`.
La excepción escapó del task `kateto-mixer` ("Task exception was never
retrieved"), el mixer murió y el bus siguió levantado pero sin salida de audio.

### Impacto

Silencio permanente hasta reiniciar; el runtime no se entera.

### Causa

La escritura al stream dentro de `_run_mixer` no estaba protegida: un error de
host de PortAudio mata el task y nadie reabre el stream.

**Solución aplicada:**

1. La escritura del mixer quedó envuelta en try/except (`PortAudioError`,
   `ValueError`, `AudioOutputDeviceError`): se descarta el chunk, se cierra el
   stream corrupto y la siguiente iteración reabre uno nuevo.
2. Guard de último recurso `except Exception` en `_run_mixer` para que ningún
   error escape como excepción no recuperada.

**Archivos:** `kateto/plugins/audio_output/player.py`
