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

## Regla OBS

Controlar OBS por **WebSocket** (puerto 4455, auth challenge-response sha256, NO HMAC), nunca por clicks ciegos. Para capturar el overlay usar "Captura de ventana" apuntando a chromium, no display capture (da negro).
