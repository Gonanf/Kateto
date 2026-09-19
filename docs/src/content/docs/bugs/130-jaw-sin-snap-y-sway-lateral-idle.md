---
id: 130
title: "Jaw sin snap (seno suave + transición CSS) y sway lateral del idle en silencio"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-09-19
---

## 130. Jaw sin snap (seno suave + transición CSS) y sway lateral del idle en silencio

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`

### Descripción

Dos defectos medidos en la animación del jaw:

1. **Sin snap:** la mandíbula se veía "demasiado suave". Dos causas reales: las capas
   `.layer-jaw` (`transition: transform 0.04s ease-out`) y `.layer-head`
   (`transition: transform 0.05s ease-out`) re-suavizaban cada frame del
   `requestAnimationFrame` (50 ms de lag por frame), y `computeJawKinematics()`
   usaba un seno puro y simétrico (`flap = 0.5 + 0.5·sin(2π·9·t)`): sube y baja
   igual de lento.
2. **Sway lateral en silencio:** `IdleMotion.update()` devolvía
   `jawOffsetX = sway` (±14 px) y `combineIdleWithVoice()` lo sumaba con escala 1.0
   justo cuando NO se habla (`s = speaking ? 0.5 : 1.0`). Además `setJawTransform()`
   sumaba el idle por su cuenta: dos caminos inyectando el lateral.

### Impacto

- Hablando, la boca abría/cerraba "como en cámara lenta" en vez de morder las sílabas.
- En silencio, la mandíbula se corría de lado a lado (±14 px) con la boca cerrada.

### Causa

- (1) Transición CSS sobre `transform` combinada con escritura por frame + envolvente
  simétrica sin ataque.
- (2) El idle aportaba `jawOffsetX` con plena amplitud en silencio, por dos caminos
  independientes (`combineIdleWithVoice` y `setJawTransform`).

### Solución aplicada

Convención de signos intacta (bugs 112 y 125): negativo = capa de arriba sube = abre;
silencio = 0 exacto. Topes de amplitud intactos.

1. **Snap:** `transition: none` en `.layer-jaw` y `.layer-head` (el snap se hace en la
   cinemática, no en CSS). Envolvente ASIMÉTRICA attack/release en
   `computeJawKinematics()`: subida rápida al máximo en `JAW_ATTACK_MS = 30`
   (ease-out, ~30 ms) y cierre lineal lento en el resto del ciclo (~81 ms a 9 Hz).
   Función continua del tiempo (interpolada entre frames, sin saltos discretos):
   toca el neutro 2 veces por ciclo, escala con rms, 0 exacto bajo el umbral 0.015.
2. **Sin lateral del idle NUNCA:** `IdleMotion.update()` devuelve `jawOffsetX = 0`
   exacto (igual que Y); `combineIdleWithVoice()` ya no suma `idle.jawOffsetX`
   (el lateral sale solo de la voz); `setJawTransform()` delega en
   `combineIdleWithVoice` (una sola fuente de pose idle, sin reinyección).
   Giro del idle conservado pero de ±8° a ±3° (`IDLE_TILT_DEG`).

**Medición** (rms 0.5 fijo, muestreo 1 ms sobre un ciclo de 111 ms):

| Métrica | Antes (seno + CSS) | Después (attack/release, sin CSS) |
|---|---|---|
| Subida al pico | ~55 ms (simétrica) | **30 ms** |
| Bajada al neutro | ~55 ms | **81 ms** |
| Pico | ~-24 px (seno^1.25) | **-27.67 px** (= -factor·40) |
| Salto máx. entre frames (1 ms) | — | **1.81 px** (continuo) |
| Cruces de nivel medio por s | ~18 | **~18** (2 por ciclo) |
| `jawOffsetX` idle en silencio | ±14 px | **0 exacto** |
| Giro idle máx. | ±8° | **±3°** |

**Tests:** 4 nuevos en `kateto/tests/test_visual_overlay.py` (idle en silencio → X e Y
0 exactos con cualquier rng + voz intacta; subida < bajada con rms fijo; rms < 0.015 →
0 exacto; `.layer-jaw`/`.layer-head` sin transición de transform) + 2 asserts del
`.mjs` actualizados al comportamiento nuevo (X idle 0, convergencia solo en rotación).

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/tests/test_visual_overlay.py`
