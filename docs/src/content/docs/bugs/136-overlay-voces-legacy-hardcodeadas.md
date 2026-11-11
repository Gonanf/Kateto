---
id: 136
title: "Visual overlay muestra voces legacy (jane/doktor/conquest/whisperer) aunque estén fuera de config"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/index.html
resolved: 2026-11-08
---

## 136. Visual overlay muestra voces legacy aunque estén fuera de config

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/plugins/system/http_server.py`

### Descripción

El overlay renderizaba tarjetas de `jane`, `doktor`, `conquest` y `whisperer` al abrir
la página, aunque esas voces ya no existan en `~/.config/kateto/voices/` (están
`enabled = false` y las activas son `dionisio`, `elchacal`, `elgarca`, `pagliacci`,
`truman`). El avatario quedaba en pantalla sin que ninguna voz lo alimentara.

### Impacto

Ruido visual permanente en OBS/pantalla: avatares fantasma que nunca hablan.

### Causa

La lista de voces del overlay vivía **hardcodeada en el cliente**
(`defaultVoices = ['jane','doktor','conquest','whisperer']` en `index.html:359`) y el
servidor nunca le pasaba la lista real al conectar. El plugin tenía
`self._voices = [...]` con el mismo default, pero ese campo no se enviaba a la página:
el único camino real era un evento `overlay_layout` con `voices`, que nada emitía
en el arranque (los avatares se iban agregando de a uno recién cuando hablaban).

`GET /voices` sí devolvía la lista real (`pagliacci`, `truman`, `dionisio`, `elgarca`,
`elchacal`), pero la página nunca lo consultaba.

### Solución aplicada

- `/ws/overlay` en `http_server.py`: al aceptar la conexión manda
  `{"event":"overlay_layout","voices":[<voces reales del manager>]}` — mismo criterio
  que `/voices` (plugins con capability `voice`, o sea solo las habilitadas).
- `index.html`: `defaultVoices = []` (arranca sin tarjetas y las puebla con el push
  del servidor). El filtro `?voices=` de la URL sigue ganándole al push.

Verificado: primer mensaje del WS es
`{"event":"overlay_layout","voices":["pagliacci","elchacal","dionisio","truman","elgarca"]}`;
`/overlay` servido tiene `defaultVoices = []`; 43 tests de overlay/ws/discussion/word-sync passed.

### Archivos

`kateto/plugins/system/http_server.py`, `kateto/plugins/visual_overlay/web/index.html`
