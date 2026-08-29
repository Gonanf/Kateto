---
id: 65
title: "Desincronización de subtítulos con el audio TTS por emisión prematura de tokens LLM"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/visual_overlay_plugin.py, kateto/plugins/visual_overlay/web/index.html, kateto/core/event.py
resolved: 2026-08-29
---

## 65. Desincronización de subtítulos con el audio TTS por emisión prematura de tokens LLM

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/plugins/visual_overlay/web/index.html`, `kateto/core/event.py`

### Descripción

El overlay visual de avatar/subtítulos consumía eventos `text_chunk` tan pronto como el LLM generaba tokens. Dado que el LLM genera texto a alta velocidad (en 1–2 segundos), los subtítulos iban reemplazándose a toda prisa en la pantalla antes de que el motor de TTS siquiera comenzara a reproducir el audio por los altavoces.

### Impacto

- Los subtítulos desaparecían o saltaban a la última oración casi al instante, imposibilitando su lectura.
- Disociación completa entre lo que se escuchaba y lo que mostraba el overlay.

### Causa

El overlay mostraba el texto directamente del stream del modelo lingüístico en lugar de sincronizarse con la reproducción del canal de audio.

**Solución aplicada:**

1. En `kateto/core/event.py`: Se extendió `AudioOutput` con el atributo opcional `text: str | None = None`.
2. En `kateto/plugins/audio_output/camb.py` y `kateto/plugins/audio_output/player.py`: Cada segmento de audio sintetizado y reproducido lleva consigo la frase de texto correspondiente.
3. En `VisualOverlayPlugin` y `web/index.html`: El overlay muestra y actualiza el subtítulo en el momento exacto en que comienza la reproducción del audio por los altavoces (evento `viseme` con `text`), manteniéndolo visible mientras se habla y limpiándolo suavemente tras 3.5 segundos de silencio posterior.

**Archivos:** `kateto/core/event.py`, `kateto/plugins/audio_output/camb.py`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/plugins/visual_overlay/web/index.html`
