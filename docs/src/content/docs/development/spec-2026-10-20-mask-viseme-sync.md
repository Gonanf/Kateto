---
title: "2026 10 20 Mask Viseme Sync"
description: "Spec de implementación — 2026 10 20 Mask Viseme Sync."
---

# Spec: evento `viseme` + sync de animación en el teléfono

Fecha: 2026-10-20 | Worktree: wt/mask-06-delta | Alcance: **pantalla del teléfono únicamente**

## 1. Alcance

El teléfono **ES** la cara de la máscara. Este card entrega sólo animación en
pantalla: el evento `viseme` en el bus y el módulo JS que lo consume. **NADA de
servos físicos, Arduino ni ESP32** — no hay plugin de servo, protocolo binario ni
firmware en este alcance.

## 2. Contrato del evento `viseme`

`VisemeData` en `kateto/core/event.py` (frozen + strict, `EventModel`).

| Campo | Tipo | Rango / default | Notas |
| --- | --- | --- | --- |
| `voice_id` | `str \| None` | `None` | voz que habla |
| `sequence` | `int` | `>= 0`, `0` | contador por emisión, monótono |
| `rms` | `float` | `0.0 .. 1.0`, `0.0` | energía normalizada (RMSProcessor) |
| `is_speaking` | `bool` | `False` | `rms > 0.05` |
| `jaw_offset_x` | `float` | `0.0` | lateral (determinista) |
| `jaw_offset_y` | `float` | `0.0` | negativo = capa de arriba sube = abre |
| `jaw_rotation` | `float` | `0.0` | tilt de mandíbula |
| `head_offset_y` | `float` | `0.0` | positivo = pieza de abajo baja |
| `audio_ms` | `float \| None` | `None` | tiempo de reproducción de la lane |
| `timestamp_us` | `int` | `>= 0`, `0` | `time.monotonic_ns() // 1000` |

Todos con default para no romper otros emisores. La cinemática sale de
`map_rms_to_puppet_transform` (`kateto/core/rms.py`), la misma que ya alimenta
`VisualOverlayPlugin.update_viseme`.

## 3. Flujo

```
player._send_viseme → evento `viseme` → (WS /ws/mask, MASK-2) → mask.html
(MASK-1) → createVisemeAnimator(avatar)
```

Este card entrega el módulo (`mask-viseme-bridge.js`) y el evento
(`VisemeData` + emisión en `player._send_viseme`).

## 4. Constantes de animación

| Constante | Valor | Por qué |
| --- | --- | --- |
| `ATTACK_MS` | `30` | subida de mandíbula rápida (snap, inercia física) |
| `RELEASE_MS` | `120` | bajada con inercia, más lenta |
| `TARGET_FPS` | `60` | 60 fps en la GPU del teléfono |

La interpolación es exponencial por coordenada con `tau` según se abra
(`ATTACK_MS`) o se cierre (`RELEASE_MS`); `dt` acotado a 100 ms. `setEyeOffset`
es un hook opcional: los ojos siguen `headOffsetY / 2.6`.

## 5. Presupuesto de latencia < 50 ms

Se mide `firstRenderLatencyMs`: `lastRenderMs - lastPushMs` del primer frame tras
cada `push` (objetivo <= 50 ms, o sea 1–3 frames a 60 fps). Se verifica con el
test `mask-viseme-bridge.test.mjs` caso 6 (frames de 16 ms → latencia <= 50).

## 6. Qué falta y de quién depende

| Falta | Depende de |
| --- | --- |
| Broadcast por `/ws/mask` | MASK-2 |
| Montaje en `mask.html` (import del módulo, `new WebSocket`, `animator.push`) | MASK-1 |
