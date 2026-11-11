---
id: 140
title: "/mask renderiza un avatar invisible (pide la voz legacy `doktor`) y /courtroom no tiene viewport meta"
severity: Media
status: open
component: kateto/plugins/visual_overlay/web/mask.html, courtroom.html
---

## 140. `/mask` avatar invisible y `/courtroom` sin viewport meta

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/mask.html`, `kateto/plugins/visual_overlay/web/courtroom.html`

### Descripción

Observado al verificar el overlay en el navegador (1920 y 390). Las dos páginas siguen
pidiendo voces que ya no existen y assets que no están:

- `/mask`: `<kateto-avatar voice="doktor">`. `doktor` está `enabled = false` y no tiene
  `avatar_head.png` ni `top.png` en `~/.config/kateto/voices/doktor/`, así que las tres
  capas fallan y la página queda **sin avatar visible** (`png: none`, `fallback_loaded: false`,
  `fallback_src: /voices/doktor/top.png`).
- `/mask` tiene además la lista `VOICES = ['doktor','jane','whisperer','conquest']` hardcodeada.
- `/courtroom`: sin `<meta name="viewport">`, en un device de 390 px el ancho de layout es
  **980 px** (medido `innerWidth = 980`), y sus 4 `<kateto-avatar>` quedan con `width = 0`
  hasta que arranca un debate (comportamiento normal en reposo, pero el viewport no).

### Impacto

`/mask` es una de las superficies servidas que quedan rotas: no muestra ninguna cara. El
`/courtroom` en teléfono renderiza zoom-out.

### Causa

Mismo origen que el bug 136: las páginas secundarias siguen cableadas a los nombres de voz
de la era Jane/Doktor/Conquest/Whisperer, mientras el overlay ya deriva las voces reales del
manager (`/voices`). Además `mask.html`/`courtroom.html` quedaron fuera del fix de viewport
que se aplicó a `index.html` (bug 137).

### Posible solución

1. `/mask`: derivar las voces de `GET /voices` (igual que el overlay) y arrancar en la
   primera voz habilitada en vez de `doktor`.
2. `/courtroom`: agregar `<meta name="viewport" content="width=device-width, initial-scale=1">`.
3. Borrar las listas hardcodeadas de nombres legacy en ambas páginas.

**Archivos:** `kateto/plugins/visual_overlay/web/mask.html`, `courtroom.html`
