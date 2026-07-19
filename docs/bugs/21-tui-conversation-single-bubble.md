---
id: 21
title: "TUI conversation tab: todas las respuestas de una voz se escriben en la primera burbuja"
severity: Media
status: resolved
component: kateto/plugins/system/tui.py
resolved: 2026-07-19
---

## 21. TUI conversation tab: todas las respuestas de una voz se escriben en la primera burbuja

**Severidad:** Media
**Componente:** `kateto/plugins/system/tui.py`

### Descripción

En el tab de Conversation del TUI, cuando una voz habla múltiples veces, todos los mensajes aparecen en la primera burbuja de esa voz. El contenido se actualiza in-place en lugar de crear una nueva burbuja.

### Impacto

- Cada voz solo tiene un único speech bubble que se sobreescribe con cada nueva respuesta.
- El historial de conversación se pierde — solo se ve la última respuesta.

### Causa

`_handle_text_chunk()` usaba `bubble_id = f"bubble-{voice}"`. Tras el `final=True`, el bubble permanecía en el DOM con el mismo ID. La siguiente tanda de `text_chunk` encontraba el bubble existente y lo actualizaba con `update()` en lugar de crear uno nuevo.

### Solución aplicada

Agregado contador `_voice_bubble_seq` por voz. Cada voz tiene un sequence number que incrementa al recibir `chunk.final`. El bubble ID ahora es `bubble-{voice}-{seq}`, asegurando que cada utterance tenga su propio bubble.

**Archivo modificado:** `kateto/plugins/system/tui.py` (líneas 177, 447-458)
