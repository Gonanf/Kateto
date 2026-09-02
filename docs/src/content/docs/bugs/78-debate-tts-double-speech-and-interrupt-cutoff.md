---
id: 78
title: "Debate TTS double speech and audio playback interruption cutoff"
severity: Alta
status: resolved
component: kateto/plugins/system/http_server.py
resolved: 2026-09-01
---

## 78. Debate TTS double speech and audio playback interruption cutoff

**Severidad:** Alta
**Componente:** `kateto/plugins/system/http_server.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/audio_output/player.py`

### Descripción

Al ejecutar un debate en Kateto con el backend de EdgeTTS activado:
1. El TTS hablaba dos veces consecutivas el mismo argumento o intervención.
2. Al ocurrir una objeción o interrupción, el TTS no se cortaba de inmediato sino que continuaba reproduciendo el audio restante hasta terminar.

### Causa

1. **Doble emisión de audio:**
   En `kateto/plugins/system/http_server.py`, el websocket handler del overlay (`/ws/overlay`) contenía un bloque que, al recibir cualquier evento de debate (`{"event": "debate", "voice_id": ..., "text": ...}`), emitía un nuevo evento `text_chunk` en el bus de eventos de Kateto. Dado que el flujo nativo del debate ya había generado y transmitido el `text_chunk` a través de los agentes de voz (habiendo sintetizado y reproducido el audio la primera vez), la llegada del mensaje al websocket del overlay provocaba que `http_server` volviera a disparar la síntesis completa por segunda vez.
2. **Falla de interrupción instantánea:**
   - En `EdgeTTSAudioOutput`, `_emit_pcm` emitía los eventos de `AudioOutput` con `voice_id=out_voice_id` (la voz neural de EdgeTTS, ej: `"es-AR-ElenaNeural"`) en vez de conservar el `data.voice_id` del agente (`"doktor"`, `"jane"`). Cuando se producía una interrupción, `AudioOutputPlayer` registraba la voz interrumpida como `"doktor"`, pero los bloques de audio entrantes llegaban con `voice_id="es-AR-ElenaNeural"`, fallando la comprobación de descarte.
   - En `SoundDeviceOutputStream`, sólo se utilizaba `stream.stop()`, el cual por especificación de PortAudio espera a que todos los bloques en el buffer del driver de audio terminen de sonar antes de detenerse. No existía llamada a `stream.abort()`.
   - `EdgeTTSAudioOutput` no drenaba su cola interna ni abortaba de inmediato al recibir `on_interrupt`.
3. **Spam en el bus de eventos y logs:**
   `AudioOutputPlayer` emitía un evento `audio_output` en broadcast hacia todo el bus de eventos cada 20ms de audio reproducido (50 eventos por segundo) únicamente para notificar el RMS a `visual_overlay`. Esto saturaba las colas de plugins no relacionados (`turn_gate`, `audio_input_mic`) e inundaba los logs con cientos de líneas DEBUG por segundo.

### Solución aplicada

1. Se eliminó la re-emisión redundante de `text_chunk` en el websocket del overlay dentro de `kateto/plugins/system/http_server.py`.
2. Se corrigió `EdgeTTSAudioOutput` (`kateto/plugins/audio_output/edgetts.py`) para:
   - Preservar `voice_id=data.voice_id` en los eventos `AudioOutput`.
   - Limpiar la cola de trabajo y cancelar tareas activas inmediatamente en `on_interrupt`.
   - Comprobar `self._interrupted` antes y durante la emisión de bloques PCM.
3. Se añadió el método `abort()` a `SoundDeviceOutputStream` en `kateto/plugins/audio_output/player.py` para invocar `stream.abort()` de PortAudio, silenciando los buffers de hardware de inmediato sin esperar a que se vacíen.
4. Se agregó el handler `on_interrupt` en `VisualOverlayPlugin` y en el cliente frontend (`BrowserPcmPlayer.stop()`, `courtroom.html`, `index.html`) para cortar la reproducción web de inmediato ante una objeción.
5. Se reemplazó la emisión de eventos `audio_output` cada 20ms en el bus de eventos por un canal directo de capa de datos (`_send_viseme` -> `VisualOverlayPlugin.update_viseme`), eliminando por completo el spam de 50 eventos/segundo en el bus de eventos y en los logs.

**Archivos:** `kateto/plugins/system/http_server.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/visual_overlay/web/index.html`, `kateto/tests/test_edgetts_interruption.py`
