---
id: 75
title: "Visual overlay: soporte para reproducción de audio TTS en navegador y layout multi-agente configurable"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/
resolved: 2026-08-31
---

## 75. Visual overlay: soporte para reproducción de audio TTS en navegador y layout multi-agente configurable

**Severidad:** Media  
**Componente:** [`kateto/plugins/visual_overlay/`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/) (`visual_overlay_plugin.py`, `web/index.html`, `web/courtroom.html`, `web/kateto-avatar.js`)

### Descripción

1. El overlay visual en el navegador (`index.html` y `courtroom.html`) no reproducía el audio del TTS directamente a través de la pestaña web, dependiendo únicamente de la tarjeta de sonido del host (`audio_output_player`). Quienes abrían el overlay en un navegador remoto o como fuente de navegador en OBS no escuchaban el TTS.
2. El overlay básico solo mostraba un avatar en pantalla en el centro y no era configurable para ver a múltiples agentes simultáneamente.

### Causa

- `VisualOverlayPlugin.on_audio_output` solo transmitía metadatos de visemas (`rms`, offsets de mandíbula, texto), omitiendo las muestras de audio PCM generadas por los motores TTS (Boson, Edge TTS, Camb AI, Zonos).
- El archivo `index.html` tenía un diseño estático con un único contenedor VTuber centrado que mutaba de avatar en vez de presentar a todos los agentes del equipo.

### Solución aplicada

1. **Streaming de Audio PCM a través de WebSocket:**
   - En [`VisualOverlayPlugin.on_audio_output`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/visual_overlay_plugin.py), se empaquetan las muestras PCM en base64 junto con los metadatos de formato (`pcm_s16le`, `sample_rate`, `channels`).
   - Se añadió [`BrowserPcmPlayer`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/web/kateto-avatar.js) usando la Web Audio API (`AudioContext`) en el frontend de `index.html` y `courtroom.html`.
   - Se incluyó un botón flotante interactivo `[ 🔊 Audio: ON / OFF ]` para desbloquear y controlar el audio del navegador sin interferir si se usa en la misma máquina física.
2. **Layout Multi-Agente Configurable:**
   - Se renovó [`index.html`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/visual_overlay/web/index.html) para soportar tanto modo Multi-Agente (`multi`, fila con todos los agentes en pantalla con animación de mandíbula independiente y resaltado del orador activo) como modo Orador Único (`single`).
   - Se permite configuración flexible por tres vías:
     1. Parámetros URL: `?mode=multi&voices=jane,doktor,conquest,whisperer&audio=1`
     2. Configuración TOML: `[plugin.visual_overlay]` con `layout = "multi"`, `voices = [...]`, `audio = true`
     3. Controles en pantalla: Barra flotante `[ 👥 Modo: Multi/Single ]` con desvanecimiento automático para transmisiones limpias en OBS.

**Archivos:** `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/plugins/visual_overlay/web/index.html`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/tests/test_visual_overlay.py`
