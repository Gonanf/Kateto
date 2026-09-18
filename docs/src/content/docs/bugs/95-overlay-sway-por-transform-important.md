---
id: 95
title: "Overlay: `.speaking` con `transform: scale() !important` desplaza la tarjeta entera al hablar"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/index.html
resolved: 2026-09-17
---

## 95. Overlay: `.speaking` con `transform: scale() !important` desplaza la tarjeta entera al hablar

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/index.html`

### Descripción

Al hablar, el personaje COMPLETO se balanceaba a la derecha y volvía al callar. No era la mandíbula (capa `jaw`, que sí tiene jitter aleatorio intencional): era toda la `.agent-card`.

### Impacto

El avatar "baila" lateralmente en cada intervención; muy visible en layout `row`.

### Causa

Las tarjetas se posicionan con `transform: translateX(-50%)` inline, pero `.agent-card.speaking` imponía `transform: scale(1.06) !important`, **reemplazando** el translate de centrado durante todo el habla (media tarjeta de ancho hacia la derecha en `row`, hacia abajo en `sides`).

### Solución aplicada

Propiedad independiente `scale: 1.06` (sin `!important`), que compone con el `transform` de posicionamiento en vez de reemplazarlo; `scale` añadido a la transición.

### Distinción registrada (2026-09-17, reporte del usuario)

- ✅ **Correcto e intencional:** la MANDÍBULA (`jawOffsetX` ±6px, `jawRotation` ±34° aleatorios en `computeJawKinematics`) se sacude de lado a lado — estilo muppet.
- ❌ **El bug:** el PERSONAJE COMPLETO (`.agent-card`) se desplazaba a la derecha — eso era el `transform` sobrescrito, no la mandíbula.

No volver a "arreglar" el sway de la mandíbula: solo el de la tarjeta.

**Archivos:** `kateto/plugins/visual_overlay/web/index.html`
