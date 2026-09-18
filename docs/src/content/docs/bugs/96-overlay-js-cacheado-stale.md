---
id: 96
title: "Overlay sirve el JS sin `Cache-Control` y el navegador ejecuta cinemática vieja"
severity: Baja
status: resolved
component: kateto/plugins/system/http_server.py
resolved: 2026-09-17
---

## 96. Overlay sirve el JS sin `Cache-Control` y el navegador ejecuta cinemática vieja

**Severidad:** Baja
**Componente:** `kateto/plugins/system/http_server.py`

### Descripción

Tras revertir la cinemática experimental de la mandíbula a la original, el overlay seguía mostrando el comportamiento viejo (movimiento hacia arriba escaso, sin sway): el navegador tenía cacheado `kateto-avatar.js`, servido vía `FileResponse` sin headers de caché.

### Impacto

Cambios del overlay parecen no tener efecto; diagnósticos erróneos ("la mandíbula se mueve poco").

### Causa

`/overlay`, `/courtroom` y `/components/{file}` no enviaban `Cache-Control`.

### Solución aplicada

`Cache-Control: no-store` en las tres rutas. Tras un hard-reload inicial (Ctrl+Shift+R o refrescar el browser-source de OBS), los cambios aplican siempre.

**Archivos:** `kateto/plugins/system/http_server.py`
