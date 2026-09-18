---
title: Overlay visual (muppet cutout)
description: "El overlay visual de Kateto: avatar con boca que reacciona al audio en OBS."
---

# Overlay visual

Kateto tiene un **overlay visual** para OBS: un avatar (muppet cutout) con dos capas — cabeza fija y mandíbula móvil — que reacciona al RMS del audio reproducido.

## Arquitectura

- `GET /overlay` — HTML del overlay (Datastar v1.0.2 por CDN).
- `GET /voices/{name}/{file}` — sprites (allowlist jane/doktor/conquest × top.png/mouth.png, 404 sin traversal).
- `WS /ws/overlay` — stream de eventos; el payload `audio_output` lleva el RMS.
- Datastar aplica `data-style-transform` (translateY + rotate sobre la mandíbula).

## Sprites

Los sprites viven en `~/.config/kateto/voices/{name}/`. Son **stock elegidos por el usuario**, generados offline — el runtime NO genera assets, solo los consume.

## Convención de signos (bug 125 — no invertir)

La capa que se anima (`.layer-jaw`, `avatar_jaw.png`) es la mitad de **ARRIBA** de la cabeza; `.layer-head` (`avatar_head.png`) es la de **ABAJO** y queda fija.

- `jawOffsetY` **NEGATIVO** = la capa de arriba **SUBE** = boca que abre. Neutro = 0 = cerrada. Positivo la baja y la boca se cierra/hunde.
- `headOffsetY` **POSITIVO** leve (máx 1.8 px) = la pieza de abajo baja = ayuda a abrir. Nunca negativo al hablar.
- Silencio = 0 exacto en ambos, sin piso fijo. Tope del jaw: 32 px hacia arriba.
- Fuente única: `SHARED CONVENTION` en `kateto/plugins/visual_overlay/web/kateto-avatar.js`; el backend (`kateto/core/rms.py`) usa el mismo signo.

## Regla OBS

Controlar OBS por **WebSocket** (puerto 4455, auth challenge-response sha256, NO HMAC), nunca por clicks ciegos. Para capturar el overlay usar "Captura de ventana" apuntando a chromium, no display capture (da negro).
