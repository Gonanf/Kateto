---
id: 128
title: "Avatar idle estático: sin voz no hay ningún movimiento, y el recorrido del jaw quedaba corto"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-09-18
---

## 128. Avatar idle estático: sin voz no hay ningún movimiento, y el recorrido del jaw quedaba corto

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/core/rms.py`

### Descripción

Pedido del usuario: *"aumenta más el movimiento del Jaw y además que por cada segundo cambie de
rotación y se mueva hacia allí, por qué está demasiado estático"*. Dos problemas:

1. **Recorrido corto (A):** con el tope de 32 px (`JAW_MAX_TRAVEL_PX`), a voz fuerte la subida
   máxima medida era ~28 px y la media ~10 px: seguía pareciendo poco.
2. **Reposo congelado (B):** `computeJawKinematics` sólo hace algo si hay RMS. En silencio todo era
   0 y no existía ninguna animación idle: el avatar quedaba totalmente estático.

### Impacto

- Overlay OBS: la boca abría menos de lo esperado a voz fuerte.
- Sin voz el avatar parecía una imagen fija; no se percibía "vivo" ni presente en la escena.

### Causa

- (A) Tope de amplitud en 32 px compartido local/backend.
- (B) No había ninguna capa de animación independiente del RMS: el transform se seteaba sólo
  cuando llegaba voz (o quedaba en `translate(0,0)` fijo con `setRms(null)`).

**Solución aplicada:**

1. **Más recorrido:** `JAW_MAX_TRAVEL_PX` 32 → **40**, `JAW_MAX_SHAKE_PX` 12 → **16**,
   `HEAD_BOB_PX` 1.8 → **2.6** (espejado en `map_rms_to_jaw_transform` /
   `map_rms_to_puppet_transform` de `kateto/core/rms.py`). Convención de signos intacta (bugs 112
   y 125): negativo = capa de arriba sube = abre; silencio = `jawOffsetY` 0 exacto.
2. **Idle motion (nuevo):** clase `IdleMotion` en `kateto-avatar.js`, con **rng y reloj
   inyectables** (tests deterministas, mismo patrón que fix-112):
   - Cada `IDLE_TURN_PERIOD_MS` (1000 ms) sortea un objetivo nuevo: rotación en `±IDLE_TILT_DEG`
     (8°) y sway lateral en `±IDLE_SWAY_PX` (14 px) **con el mismo signo** (se mueve hacia donde
     mira).
   - La pose se acerca al objetivo con easing exponencial (`IDLE_EASE_TAU_MS` = 300): se lee como
     un giro de cabeza, sin saltos entre frames.
   - `combineIdleWithVoice()` lo suma a la cinemática de voz: hablando se escala por
     `IDLE_SPEAKING_SCALE` (0.5, la boca es la protagonista); en silencio va a plena amplitud y
     **la boca sigue cerrada** (`jawOffsetY` 0 exacto, el idle nunca aporta Y).
   - Corre en los **dos modos** (local vía loop de render persistente en `connectedCallback` +
     `setRms`; backend vía `setJawTransform`): es movimiento de render, no depende del RMS.

**Medición antes/después** (`node script/qa/measure_jaw.mjs`, habla 1.5 s a rms 0.2/0.5/0.8):

| Métrica | Antes (tope 32) | Después (tope 40) | Objetivo |
|---|---|---|---|
| Subida máxima local | ~-28 px | **-35.54 px** | ≥ 34 px ✅ |
| Media local | ~-10 px | **-12.03 px** | ≥ 12 px ✅ |
| Cruces de nivel medio | ~15/s | **20.67/s** | ≥ 20/s ✅ |
| Silencio | 0 exacto | **0 exacto** | 0 ✅ |

**Serie idle** (6 s, muestreo cada 100 ms, rng sembrado — objetivo nuevo cada segundo y pose
acercándose):

| Segundo | Objetivo rot | Objetivo sway | Pose rot | Pose sway |
|---|---|---|---|---|
| 0 | -5.39° | -9.43 px | -5.12° | -8.96 px |
| 1 | +6.37° | +11.15 px | +5.96° | +10.44 px |
| 2 | -3.93° | -6.88 px | -3.58° | -6.26 px |
| 3 | +6.48° | +11.34 px | +6.12° | +10.71 px |
| 4 | -4.61° | -8.07 px | -4.23° | -7.40 px |
| 5 | +3.52° | +6.16 px | +3.24° | +5.68 px |

5 cambios de objetivo en 6 s; rotación y sway siempre mismo signo; `jawOffsetY` 0 exacto en toda
la serie.

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`,
`kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/core/rms.py`,
`kateto/tests/test_visual_overlay.py`, `script/qa/measure_jaw.mjs`
