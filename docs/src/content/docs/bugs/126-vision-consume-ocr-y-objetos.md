---
id: 126
title: "La voz no consume el OCR ni la detección de objetos del sidecar (opina adivinando la pantalla)"
severity: Media
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 126. La voz no consume el OCR ni la detección de objetos del sidecar

**Severidad:** Media
**Componente:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/voices/base.py`

### Descripción

Kateto sólo llamaba `describe_images` del sidecar `video-rag`; el texto de la
pantalla lo adivinaba el VLM y lo leía mal (convirtió "Teorema de existencia"
en "Tornes de existencia"). El sidecar (commit `2e559d3`, `Gonanf/video-rag`)
ya expone `ocr_images` (0.2 s) y `detect_objects` (~9 s de VLM por llamada),
pero la voz no tenía cómo opinar sobre el texto real.

### Impacto

La voz opinaba sobre contenido inventado por el VLM en vez del texto literal de
la pantalla, y el marco (bug 121/123) no la orientaba a usar el `OCR:` si lo
hubiera habido.

### Solución aplicada

1. El plugin pide `ocr_images` con los mismos frames del sidecar y suma el
   resultado al material como `OCR:`; con `vision_detect=true` agrega
   `detect_objects` como `OBJECTS:` (marcado `best-effort` cuando el backend
   contesta `via=vlm`). El material queda
   `VISUAL:` / `OCR:` / `OBJECTS:` bajo el encabezado `--- <source> ... ---`.
2. Degradación silenciosa: si el sidecar no tiene la tool (binario viejo) o
   falla, se sigue como antes con un log `debug`/`info`. El OCR va por el path
   `try_call_tool_result` que conserva `is_error` (bug 106): un error de OCR
   nunca reemplaza al caption ni se narra como texto de pantalla.
3. Knobs: `vision_ocr` (default `true`, es barato y de mayor valor) y
   `vision_detect` (default `false`, ~9 s VLM por llamada). Un look-at pedido
   por el usuario usa detección sólo si `vision_detect` está en `true`.
4. El marco de la voz (`frame_look_at_turn`, bug 121/123) dice que el texto
   literal viene en `OCR:` y que puede usarlo para opinar con sustancia, sin
   inventar lo que no está en ninguna sección. Mantiene la regla dura de
   fix-111: opinar en personaje, no repetir el literal, nunca pedir
   instrucciones.
5. Bonus: OCR idéntico al de la ventana anterior es señal de pantalla repetida;
   se usa como segundo criterio para callar la narración periódica
   (complementa el dHash de fix-111).

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/voices/base.py`, `docs/src/content/docs/plugins/vision.md`, `kateto/tests/test_vision_ocr_detect.py`