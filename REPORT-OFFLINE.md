# REPORT — Kateto offline-first (SW + manifest + fallback local)

## Archivos creados

| Archivo | Qué contiene |
|---|---|
| `kateto/plugins/system/offline_shell.py` | Módulo puro (sin FastAPI, sin manager): constantes (`SHELL_URL`, `SW_URL`, `MANIFEST_URL`, `ICON_URL`, `CACHE_PREFIX`, `SPEECH_LANG`, `ICON_SVG` = 228 bytes), `collect_offline_assets()`, `cache_name()`, `render_service_worker()`, `build_manifest()`, `phone_urls()`, `local_ipv4_addresses()` |
| `kateto/tests/test_offline_shell.py` | Los 10 tests BDD del brief, con puerto libre real (`bind(("127.0.0.1", 0))`) y `await server.stop()` en `finally` |
| `kateto/plugins/visual_overlay/web/kateto-offline.js` | ES module sin DOM a nivel top-level: `OFFLINE_FAILURE_THRESHOLD`, `createOfflineState()`, `reduceOffline()` (puro, no muta), `createOfflineShell()` (badge + `body.offline` + `speak()` es-AR + `stopSpeaking()`) |
| `kateto/plugins/visual_overlay/web/kateto-offline.test.mjs` | 7 tests con `node:test` + `node:assert/strict`, fakes de `doc`/`speech` escritos a mano (sin jsdom) |

## Archivos editados

| Archivo | Cambio |
|---|---|
| `kateto/plugins/system/http_server.py` | Import de `Response` y de `offline_shell`; rutas nuevas `GET /offline/sw.js` (con `Service-Worker-Allowed: /` y `Cache-Control: no-cache`), `GET /manifest.webmanifest`, `GET /offline/icon.svg`; en `start()`, warning si escucha en loopback + `log.info("phone url: ...")` envuelto en `try/except Exception`. **No** se tocó `NoCacheMiddleware` ni ninguna otra ruta. |
| `kateto/plugins/visual_overlay/web/index.html` | (a) `<link rel="manifest">` + `<meta name="theme-color">` después del icon; (b) CSS del badge (#offline-badge, `[hidden]`, `body.offline #caption-bar`) al final del `<style>`; (c) `<div id="offline-badge" hidden>` antes del `<script type="module">`; (d) import de `createOfflineShell`; (e) `offlineShell` + `window.katetoOffline`; (f) `ws.onopen` / `ws.onerror`; (g) `ws.onclose` con `offlineShell.update({ type: 'ws_close' })` antes del retry; (h) registro del SW al final. Nada más se tocó (layout, voces y player de audio intactos). |

`git status --porcelain` al cierre: solo esos 6 archivos (4 `??`, 2 `M`). No se creó ni borró ningún otro archivo.

## Gate 1 — pytest

```
PYTHONPATH=$PWD /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin/python -m pytest kateto/tests/test_offline_shell.py kateto/tests/test_http_server.py -q
```

Conteo: **13 passed** = 10 tests nuevos (`test_offline_shell.py`) + 3 baseline (`test_http_server.py`). Exit 0.

Tail (3 últimas líneas, literal):

```

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
13 passed, 7 warnings in 5.38s
```

(Las 7 warnings son `torch.jit` deprecatión del propio venv, no de este cambio.)

## Gate 2 — node --test

```
node --test kateto/plugins/visual_overlay/web/kateto-offline.test.mjs kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs
```

Conteo: **tests 28 / pass 28 / fail 0** = 7 nuevos (`kateto-offline.test.mjs`) + 21 baseline (`kateto-avatar.test.mjs`). Exit 0.

Tail (3 últimas líneas, literal):

```
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 95.503307
```

## Requisitos cubiertos

- **Service Worker que precachea el shell completo**: `install` con `caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting())`; `activate` borra caches con prefijo `kateto-offline-` distintos del actual y después `clients.claim()`; `fetch` responde solo GET same-origin, salta `/ws/` y `/api/`, network-first con fallback al shell en navegaciones y cache-first para el resto. Sin `importScripts`, sin workbox, sin URLs externas.
- **Manifest instalable**: `build_manifest()` servido en `/manifest.webmanifest` (`application/manifest+json`) + `<link rel="manifest">` y `theme-color` en el `<head>` + icono SVG propio en `/offline/icon.svg`.
- **Fallback local**: badge `#offline-badge` (oculto por default) que se muestra recién al tercer `ws_close`/`ws_error` consecutivo y desaparece con `ws_open`; `body.offline` atenúa `#caption-bar`. TTS local con Web Speech API: `speak()` usa `lang = 'es-AR'`, `rate = 1.0`, con `cancel()` previo y try/catch; queda expuesto en `window.katetoOffline.speak("...")` / `.stopSpeaking()`.
- **Avatar/overlay desde cache**: los `*.js` (incluido `kateto-avatar.js` con su `IdleMotion` existente) entran en el precache; no se escribió ninguna animación idle nueva.
- **Cero URLs externas**: `grep -E 'https?://'` sobre `index.html`, `kateto-offline.js` y `kateto-offline.test.mjs` → **0 hits**. En `offline_shell.py` los únicos `http://` son el namespace XML `xmlns` del SVG (no es un recurso descargado) y las URLs LAN que pide `phone_urls()`.
- **URLs de LAN**: `start()` avisa si escucha en loopback y loguea `phone url: ...` por cada mDNS/IPv4 privada, con `try/except` para que nada de red local impida levantar el server.

## Requisitos NO cubiertos

- **QR**: no estaba especificado en este brief (solo aparece como ejemplo de mención) → no se hizo, no se inventó alcance.
- **TTS local automático**: el wiring pedido por el brief no incluye ninguna llamada a `speak()` en un evento (solo badge + registro de SW + handlers de WS). El módulo lo soporta y queda expuesto en `window.katetoOffline`, pero **no hay disparador automático** de voz al entrar en offline. No agregué uno porque no estaba en la especificación.

## Decisiones fuera del brief

1. **`ignoreSearch` en el cache-first del SW.** El precache guarda URLs sin query (`/components/kateto-avatar.js`) pero `index.html` importa con versión (`?v=flap6`, `?v=offline1`); con el `caches.match(req)` literal, offline ese match fallaría y el JS del avatar (y el del offline) no se servirían desde cache, rompiendo el requisito de que el idle siga sin red. El fetch queda: match exacto → match con `{ ignoreSearch: true }` → `fetch(req)`, conservando la expresión del brief como primer paso. Fue la única desviación; nada más se decidió fuera de la card.

Ningún paquete instalado, ningún archivo borrado, `config/`, `docs/`, `kateto-wts/`, `.venv/`, `node_modules/` y tests existentes intactos.
