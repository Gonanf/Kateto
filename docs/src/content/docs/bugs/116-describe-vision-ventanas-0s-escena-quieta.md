---
id: 116
title: "Describe de visión reporta ventanas de 0 s cuando la escena está quieta"
severity: Alta
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 116. Describe de visión reporta ventanas de 0 s cuando la escena está quieta

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/static_vision_plugin.py`

### Descripción

Runtime real del usuario (16:28): con 5 frames posibles en la ventana sobrevive
**1** y el span que recibe la voz es **0 segundos**:

```
[vision] sidecar describe_images answered (48 chars)
[vision] describe requester=scheduler:jane source=auto via=sidecar frames=1/5 chars=80
[vision] periodic narration -> jane (0s window)
```

El prompt queda `[look-at auto 0s]: ...` — le decimos a la voz que miró 0 segundos.
El `1/5` es el dedupe por hash haciendo su trabajo (pantalla estática estudiando
un PDF: los 5 frames son iguales y queda 1). Lo que está mal no es el dedupe,
es el span: `section_span(kept)` devuelve `0.0` con un solo frame, y
`window_start`/`window_end` salían del `min/max` de los kept en vez de la ventana.

Segundo síntoma en el mismo log: el sidecar falló (`describe_images` respondió
un texto de error de 48 chars) y el plugin lo trató como descripción y lo narró:
la voz dijo *"Uh, qué fallo más raro. La cámara se durmió o la red se fue de
viaje."* Un error del sidecar no es una descripción.

### Impacto

La voz cree mirar 0 segundos en cada escena quieta; ante un VLM caído, la
narración ambiental repite el error como si fuera lo que vio.

### Causa

1. Span calculado sobre los frames que sobrevivieron al dedupe, no sobre la
   ventana pedida (`window_secs`) ni el rango capturado incluyendo descartados.
2. `_describe_fallback` devolvía el texto del sidecar sin distinguir error de
   descripción (el formato `video-rag describe_images: VLM unreachable at ...
   (model ...)` de `src/mcp.rs` del sidecar, y el `{"error": ...}` propio,
   llegaban como strings planos).

### Solución aplicada

- Nuevo `_window_span(frames, kept, window_secs)`: con un solo kept informa la
  ventana pedida (respeta `window_secs` del request cuando viene); con varios,
  el rango capturado. Nunca 0 con ventana positiva. Dedupe intacto.
- `window_start` = primer timestamp capturado (incluyendo descartados);
  `window_end` = `start + span`, coherentes por construcción.
- Prompt de narración: `[look-at <source> <span>s]` y, con un solo frame,
  `[look-at <source> <span>s, 1 frame]`. Nada de "0s".
- Nuevo `_is_sidecar_error(text)`: el error del sidecar se loguea **completo**
  una vez (endpoint y modelo) y cae al siguiente eslabón (fallback-vlm, si no
  recap). El recap nombra el fallo del sidecar — eso es una respuesta para el
  `look-at` del usuario — y como es `via=recap`, la narración ambiental sigue
  suprimida (bug 115) en vez de vocear el error.

**Regresión:** `kateto/tests/test_vision_window_span.py` (9 tests: escena
estática ⇒ span == ventana + nota de frames; movimiento ⇒ rango real; un solo
frame ⇒ ventana pedida; override de `window_secs`; error del sidecar ⇒
fallback/recap sin `generate` periódico; timeout JSON ⇒ no es descripción).

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`,
`kateto/tests/test_vision_window_span.py`
