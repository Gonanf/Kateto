---
id: 137
title: "Overlay recortaba avatares con 5 voces: row se salía por los bordes y sides apilaba la 3ra fila fuera de pantalla"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/index.html
resolved: 2026-11-08
---

## 137. Overlay recortaba avatares con 5 voces (row y sides)

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/index.html`

### Descripción

Con las 5 voces reales (`pagliacci`, `dionisio`, `truman`, `elgarca`, `elchacal`) el
overlay recortaba tarjetas: en `row` la primera/última quedaban fuera de pantalla, y en
`sides` la tercera fila apilada caía por debajo del borde inferior. El overlay tampoco
tenía `<meta name="viewport">`, así que en un teléfono el ancho de layout era 980 px
(zoom-out) y no el del dispositivo.

### Impacto

Avatares cortados en 1366px de ancho (laptop) y en pantalla de teléfono; en 1080p
`sides` con 5 voces también perdía la última tarjeta por abajo.

### Causa

Medido, no supuesto:

- `row` posicionaba con `left: 7% + idx * step` y `translateX(-50%)`: con avatar de
  220 px la primera tarjeta arranca en `0.07*vw - 110` → negativa para cualquier
  ancho menor a ~1570 px.
- el ancho de la tarjeta es `max(avatar, tag)`: el tag "Elchacal" medía 88 px cuando el
  avatar achicado medía 64 px, así que en 390 px la última tarjeta sobresalía 37 px
  aunque el avatar entrara.
- `sides` usaba `top: 30% + floor(idx/2)*35%`: con 5 voces (3 filas) la tercera quedaba
  en `100% - h/2`, fuera de pantalla (1080p: bottom 1198; 1366x768: 886).
- faltaba `viewport`, por eso `innerWidth` en móvil daba 980.

### Solución aplicada

- `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- `row`: N slots reales (`size = min(220, 0.92*vw/N - 8)`, piso 60 px), avatar y tag
  ajustados al slot (`item.tag.style.maxWidth = size`), y `.agent-tag` con
  `max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap`.
- `sides`: filas = `ceil(count/2)`; `top` se calcula en px con la altura real de la
  tarjeta (`half + 8 + fila * (vh - 2*half - 16)/(filas-1)`), así la última fila
  termina dentro del viewport en cualquier alto.
- Los overrides inline (`avatar`/`tag`) se resetean en cada recálculo, para que `sides`,
  `corners`, `single`, etc. vuelvan al tamaño CSS.

### Verificación observada (Chrome headless, transiciones apagadas para medir geometría final)

| viewport | layout | tarjetas | voces viejas | recortadas | avatar |
|---|---|---|---|---|---|
| 1920x1080 | row | 5 | ninguna | 0 | 220 px |
| 1920x1080 | sides | 5 | ninguna | 0 | 220 px |
| 1366x768 | row / sides | 5 | ninguna | 0 | 220 px |
| 390x844 (mobile) | row | 5 | ninguna | 0 | 64 px |
| 390x844 (mobile) | sides | 5 | ninguna | 0 | 109 px |

Sin scroll horizontal (`scrollWidth == clientWidth`) en los tres tamaños; `?voices=` sigue
filtrando (`?voices=dionisio,truman` → 2 tarjetas). 56 tests passed.

### Archivos

`kateto/plugins/visual_overlay/web/index.html`
