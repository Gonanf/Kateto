# Visión: consumir el OCR y la detección de objetos del sidecar (opinar sobre contenido real)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## REGLA 0 (leela primero)
**Prohibido explorar.** No recorras el repo, no leas tests ajenos, no hagas greps de descubrimiento.
Sólo abrí los archivos y los rangos que se nombran acá, y andá **directo al patch**. Si algo no está
donde dice, lo reportás al final; no lo salís a buscar. Los tests que tenés que escribir son los de la
sección **Tests**, nada más.

Archivos y anclas exactas:
- `kateto/plugins/executor/static_vision_plugin.py` (~1312 líneas) — donde hoy llama `describe_images`
  y arma el caption/recap; ahí van las llamadas nuevas. Los knobs se registran como en `vision_interval`.
- `kateto/plugins/system/external_mcp.py` — `call_tool_result` (conserva `is_error`) y `try_call_tool`.
- `kateto/voices/base.py` (~1573 líneas) — los marcadores de enmarcado del look-at/narración
  (`_LOOK_AT_FRAMED_MARKERS`, `frame_look_at_turn`).
- `docs/src/content/docs/plugins/vision.md` — la tabla de settings.

## Contexto (ya está hecho del otro lado)
El sidecar `video-rag` ahora expone dos tools MCP nuevas (commit `2e559d3` en `Gonanf/video-rag`,
probadas por stdio contra el binario real):

- `ocr_images {images: [data-URL], lang?}` → texto por imagen. **0.2 s** en una imagen 1000x300 con
  texto (`image 0 (1000x300):\nREUNION MARTES 14:30\n...`), con el mismo contrato de topes que
  `describe_images` (máx 8, ≤1.5MB, exceso = error nombrando la imagen).
- `detect_objects {images: [data-URL], labels?}` → `via=vlm` o `via=sidecar` + líneas
  `DETECT @ image 0: square 0.90 [86,238,430,842]`. El backend VLM (best-effort) tardó **9.2 s**.

Hoy Kateto sólo llama `describe_images`, así que el texto de la pantalla lo adivina el VLM (y lo lee
mal: convirtió "Teorema de existencia" en "Tornes de existencia"). La voz necesita el texto real para
opinar con sustancia.

## Fix esperado

### 1. El plugin de visión pide OCR (y opcionalmente detección) y compone el material
En `kateto/plugins/executor/static_vision_plugin.py`, en el mismo lugar donde hoy arma el caption con
`describe_images`:

- Llamá `ocr_images` con **los mismos frames** (data-URLs) y sumá el resultado al material de la voz.
- Llamá `detect_objects` sólo cuando corresponda (ver knobs). Si el backend contesta `via=vlm`,
  incluí igual el texto pero **marcalo como best-effort** (no lo presentes como certeza).
- El material que se emite tiene que quedar así (secciones opcionales, sólo si hay contenido):
  ```
  --- screen (5s, 1/5 frames) ---
  VISUAL: <caption del VLM>
  OCR: <líneas del texto en pantalla>
  OBJECTS: <label score [box]> ... (via=vlm: best-effort)
  ```
- **Degradación silenciosa**: si el sidecar no tiene la tool (binario viejo) o falla, se sigue como
  hoy y queda un log `debug`/`info` con el motivo. Un error de OCR **nunca** reemplaza al caption ni se
  narra como si fuera texto de la pantalla (misma regla que `isError`, bug 106).
- El OCR tiene que pasar por `call_tool_result` (el que conserva `is_error`, bug 106), no por un path
  que tire el flag.

### 2. Knobs
- `vision_ocr` (default **true**): es barato (0.2 s) y es el que más valor agrega.
- `vision_detect` (default **false**): cuesta ~9 s de VLM por llamada; se prende por voz cuando el
  usuario quiere. **Pero** un look-at pedido por el usuario (`vision_describe_request` con
  `source=user`, o el pedido explícito desde la skill `look-at`) sí usa detección si `vision_detect`
  está en true — no la inventes si está apagada.
- Documentá los dos en `docs/src/content/docs/plugins/vision.md` y en el `known-issues`/bug que
  corresponda.

### 3. El marco de la voz tiene que usar el texto
En `kateto/voices/base.py`, el marco de la narración/look-at (bug 121/123) tiene que decirle a la voz
que **el texto literal de la pantalla viene en `OCR:`** y que puede (y debe) usarlo para opinar con
sustancia, sin inventar lo que no está en ninguna sección. Mantené la regla dura de fix-111: **opinar
en personaje**, no repetir literal, y nunca pedir instrucciones ("¿qué querés que haga con esto?").

### 4. Bonus si es simple (y sólo si no ensucia el diseño)
Si el texto de OCR es **idéntico** al de la ventana anterior, eso es una señal fuerte de pantalla
repetida: podés usarlo como segundo criterio para callar la narración (complementa el dHash de
fix-111). Si complica, no lo hagas y decilo en el resumen.

## Tests
- Con un sidecar fake: `ocr_images` devuelve texto ⇒ el material lo incluye bajo `OCR:`; la tool tira
  `is_error` ⇒ no se incluye y cae al recap (no se narra como texto de pantalla); la tool no existe ⇒
  todo sigue igual que antes (test de compatibilidad con sidecar viejo).
- `vision_ocr=false` ⇒ no se llama `ocr_images` (ni una vez).
- `vision_detect=true` con fake ⇒ se incluye `OBJECTS:`; `false` ⇒ no se llama.
- El marco que recibe el modelo (asertar el texto literal) menciona `OCR:` y mantiene la prohibición de
  pedir instrucciones.

## Verificación final (sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or look_at or prompt"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **557 passed / 3 failed** (preexistentes)
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes. Cambiar el contrato de `describe_images`. Hacer que un error de OCR se narre.
- Inventar detecciones cuando `vision_detect` está apagada.
