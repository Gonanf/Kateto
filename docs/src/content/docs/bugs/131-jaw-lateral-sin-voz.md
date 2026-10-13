---
id: 131
title: "El jaw se mueve de lado a lado sin que nadie hable"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-10-01
---

## 131. El jaw se mueve de lado a lado sin que nadie hable

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/system/http_server.py`

### Descripción

Reporte del usuario: *"el Jaw se mueve de lado a lado incluso cuando no estan hablando, y solo
se tienen que mover de lado a lado de manera aleatoria en un rango cuando hablan"*.

Dos causas reales, ambas confirmadas:

1. **El lateral se sorteaba por frame y el umbral de "hay voz" era ruido de sala.**
   En `computeJawKinematics(rms, nowMs)` la guarda era `rms < 0.015` y el lateral salía de
   `sideDir = Math.random() * 2 - 1` **recalculado en cada llamada** (60-120 Hz):
   `jawOffsetX = sideDir * factor * JAW_MAX_SHAKE_PX`. El signo alternaba frame a frame, así que
   no se leía como sway sino como vibración. Y como 0.015 es ruido (tono de sala, ruido del mic,
   cola del TTS), cualquier rms por encima de ese valor entraba al camino que mueve la boca:
   con el exponente 0.52 de la curva, un rms de 0.02-0.04 ya producía 1-2.4 px de lateral.
   El backend nunca hizo esto: `map_rms_to_puppet_transform` usa piso 0.05 y devuelve
   `jawOffsetX: 0.0` siempre.

2. **Los eventos sin audio se asumían hablando.** En `/api/game/event`
   (`kateto/plugins/system/http_server.py`) el default era `0.12`:
   `float(event_data.get("rms", event_data.get("rms_hint", 0.12)) or 0.12)`. Un evento sin `rms`,
   sin `rms_hint` o con el valor vacío se procesaba con 0.12 — por encima de los dos umbrales —
   y el payload salía con `jawOffsetY: -2.95`, `jawRotation: 0.48`, `is_speaking: true` **sin
   que existiera audio**.

### Impacto

- Con la sala en silencio y el mic abierto, la mandíbula vibraba de lado a lado (ruido de sala por
  encima del umbral de 0.015).
- Un evento de juego sin dato de audio abría la boca y marcaba `speaking`.

### Causa

Umbral de habla divergente entre JS (0.015) y backend (0.05), y lateral generado con
`Math.random()` dentro de la función pura de cinemática, que se llama una vez por frame.

### Solución aplicada

Convención intacta (bugs 112, 125 y 130): `jawOffsetY` negativo = la capa de arriba sube = abre;
silencio = 0 exacto; el idle nunca aporta lateral; el tilt sigue como estaba.

1. **Un solo umbral de "hablando"**: `VOICE_MIN_RMS = 0.05` (el mismo del backend), usado tanto
   por `computeJawKinematics` como por `computeBackendKinematics` y por el check `speaking` del
   componente. Bajo ese umbral la función devuelve 0 exacto, lateral incluido.
2. **Lateral con objetivo persistente**: nueva clase `JawSwayMotion` (mismo patrón inyectable que
   `IdleMotion`: rng y reloj por parámetro) sortea un objetivo nuevo cada `JAW_SWAY_PERIOD_MS`
   (160 ms) dentro de ±`JAW_MAX_SHAKE_PX` y la pose se acerca con easing exponencial
   (`JAW_SWAY_EASE_TAU_MS` = 100 ms). El easing es monótono: dentro de un periodo la pose no puede
   cambiar de signo, así que dos frames consecutivos no tienen signo opuesto salvo que el objetivo
   haya cambiado. `computeJawKinematics` recibe la pose ya eased (`swayPx`), la escala por la
   energía de la voz y la acota a ±16 px. Cero `Math.random()` en el lateral.
3. **Backend sin audio = boca quieta**: sin `rms` ni `rms_hint` (o vacíos) el `rms` es `0.0`, y
   `map_rms_to_puppet_transform(0)` sale con todo en 0 y `is_speaking: false`.
4. **Sin cambios en el movimiento vertical**: la curva `((rms - 0.015)/0.985)^0.52` y la
   envolvente attack/release quedan como estaban (bugs 122 y 128); el bug 131 sube el umbral de la
   guarda, no la amplitud con voz. El tilt (`JAW_MAX_TILT_DEG`) tampoco se tocó.

**Medición** (`node script/qa/measure_jaw.mjs`, mismo protocolo 0.3 s silencio / 1.5 s habla /
0.4 s silencio a 60 Hz, lateral del pipeline completo con rng sembrado):

| Métrica del lateral | Antes | Después |
|---|---|---|
| Cambios de signo en 1.5 s de habla | **51** (~34 Hz) | **6** (uno por periodo) |
| Amplitud | ±12.66 px | ±11.13 px |
| Silencio inicial / final | — | **0 exacto** en todos los frames |

Con el código anterior, un barrido de `rms = 0.02` movía el lateral −0.84 px en el frame 0.

**Tests:** 5 nuevos en `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` (barrido de rms
bajo el umbral → X 0 exacto; 2 s de silencio con idle → X 0 exacto en todos los frames; con voz
|X| ≤ `JAW_MAX_SHAKE_PX` y se mueve de verdad; cambios de signo ≤ 1 por periodo; un objetivo fijo
no puede cambiar de signo entre frames) + 1 nuevo en `kateto/tests/test_visual_overlay.py`
(`/api/game/event` sin `rms` y con `rms` vacío no producen movimiento de jaw, con control positivo
de que rms 0.5 sí mueve la boca).

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`,
`kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/plugins/system/http_server.py`,
`kateto/tests/test_visual_overlay.py`, `script/qa/measure_jaw.mjs`