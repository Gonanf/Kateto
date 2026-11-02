---
title: "132 — El idle rota el jaw: la boca se mece de lado a lado en silencio"
description: "Bug 131 mató el lateral por translate, pero el idle seguía rotando la capa del jaw ±2.5°: se lee como mandíbula que se mueve sin hablar."
---

**Estado:** resuelto (2026-11-02) · `kateto/plugins/visual_overlay/web/kateto-avatar.js`

## Síntoma

Reportado por el operador: "el jaw se mueve lado a lado siempre, incluso cuando el
agente no habla". El bug 131 ya había dejado `jawOffsetX === 0` en silencio, así que
la medición de siempre (translate) daba limpio y el bug seguía vivo.

## Causa

`IdleMotion` seguía aportando **rotación** a la capa del jaw
(`{ jawRotation: this._pose.rotation }`, ±3° con `IDLE_TILT_DEG = 3.0`), y
`combineIdleWithVoice` la sumaba en silencio a plena amplitud. Una rotación de 2–3°
sobre la pieza superior se lee como mandíbula yéndose de lado, aunque el translate
sea 0 exacto.

Medido en `/mask` con el código de entonces (25 muestras cada 120 ms, sin audio):

```
jaw translate: (0, 0) en todas las muestras
jaw rotate:    -2.32° .. +2.62°
```

El segundo intento —mover el tilt a la pieza de abajo (`id="head"`)— también estaba
mal: esa capa es el cuerpo/boca completo, y rotarla gira el cuerpo entero.

## Fix

El idle **no rota ninguna capa**. Aporta solo un bob vertical lento
(`IDLE_BOB_PX = 1.5`, derivado del objetivo de rotación que ya se sorteaba cada
`IDLE_TURN_PERIOD_MS`), que se lee como respiración y no como habla. El jaw lo mueve
exclusivamente la voz.

## Verificación (medida, no impresión)

Mismo barrido en `/mask`, idle:

```
jawX 0 · jawY 0 · jawRot 0        (nada de lado, nada de rotación)
headRot 0 · headY -1.07 .. +0.67  (respiración)
```

Con voz (`setRms` 0.2–0.8 durante 1.8 s): `jawY -32.5..-0.6`, `jawX ±11`,
`jawRot ±5.5°` → la boca sigue abriendo, con lateral acotado por `JAW_MAX_SHAKE_PX`.

`node --test kateto-avatar.test.mjs`: 21/21.

## Trampa al verificar

El server sirve el JS con `Cache-Control: no-store`, pero un Chromium ya abierto
sigue resolviendo el módulo ES desde su caché en memoria: hay que recargar con
`Network.setCacheDisabled` + `Page.reload(ignoreCache)`. Sin eso se mide el código
viejo y el bug "sigue".
