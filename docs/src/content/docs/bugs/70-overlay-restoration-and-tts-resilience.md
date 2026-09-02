---
id: 70
title: "Restauración del Visual Overlay básico y resiliencia del estado de interrupción en AudioPlayer y Camb.ai"
severity: Alta
status: resolved
component: kateto/plugins/visual_overlay/web/index.html, kateto/plugins/audio_output/player.py, kateto/plugins/audio_output/camb.py
resolved: 2026-08-31
---

## 70. Restauración del Visual Overlay básico y resiliencia del estado de interrupción en AudioPlayer y Camb.ai

**Severidad:** Alta
**Componente:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/camb.py`

### Descripción

1. **Contaminación del Visual Overlay Básico:** `index.html` (diseñado como overlay transparente para streaming/OBS con Datastar y caja de subtítulos simple `#caption`) había sido reemplazado por componentes del tribunal (`<kateto-subtitles>`), adoptando el estilo visual del courtroom.
2. **Bloqueo del TTS:**
   - En `player.py`, la bandera `self._interrupted` y `self._interrupted_voice` no se restablecían al cerrarse el stream interrumpido ni con la llegada de `data.final`. Si la misma voz hablaba nuevamente o si la voz interrumpida recibía nuevo audio, el condicional `data.voice_id == self._interrupted_voice` bloqueaba indefinidamente todo el audio posterior.
   - En `camb.py`, `on_text_chunk` cancelaba activamente cualquier tarea en ejecución de manera incondicional. En modos de streaming donde los fragmentos de la misma voz llegan sucesivamente (`seq=0, seq=1`), cada fragmento cancelaba al anterior impidiendo que la síntesis completara.
   - En `courtroom.html`, tras retirar `<kateto-subtitles>`, la síntesis por Web Speech API del navegador se había desactivado al residir dentro de dicho componente.

### Impacto

- El overlay básico de VTuber para OBS mostraba la interfaz del tribunal y no su diseño transparente original.
- El motor TTS no reproducía audio tras una interrupción o en streaming token-a-token.
- La página `/courtroom` no reproducía audio si el runtime de backend no estaba corriendo.

### Solución aplicada

1. **Restauración de `index.html`:** Se devolvió `index.html` a su implementación original pura con Datastar, capas de mandíbula y cabeza cinemática, y subtítulos flotantes oscuros `#caption` transparentes para OBS.
2. **Resiliencia en `player.py`:**
   - Se limpia `self._interrupted = False` y `self._interrupted_voice = None` inmediatamente al cerrar el stream tras la interrupción y al recibir `data.final`.
   - Se midió la ventana de descarte de paquetes residuales (`now - self._interrupted_at < 0.6s`) para asegurar que una voz nunca quede silenciada de manera permanente.
3. **Manejo de streaming en `camb.py`:**
   - Se eliminó la cancelación incondicional de stream en `on_text_chunk`. Solo se cancela la tarea si ocurrió un evento `interrupt` o si una voz distinta corta a la voz actual en curso.
4. **Síntesis por Web Speech API en `courtroom.html`:**
   - Se añadió síntesis de voz en el navegador (`speakDebateTurn`) con auto-silenciamiento cuando se detecta audio PCM activo del backend.

**Archivos:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/plugins/visual_overlay/web/courtroom.html`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/camb.py`, `kateto/tests/test_visual_overlay.py`
