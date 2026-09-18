# Jaw más grande + la cabeza no puede estar quieta: rotación nueva cada segundo y mover hacia ahí

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## REGLA 0 (leela primero)
**Prohibido explorar.** Abrí sólo lo que está acá y andá directo al patch. Los tests a escribir son los
de la sección **Tests**.

Anclas:
- `kateto/plugins/visual_overlay/web/kateto-avatar.js` (~línea 38): `JAW_MAX_TRAVEL_PX = 32.0`,
  `JAW_MAX_TILT_DEG = 6.5`, `JAW_MAX_SHAKE_PX = 12.0`, `HEAD_BOB_PX = 1.8`, `FLAP_HZ = 9`;
  `computeJawKinematics(rms, nowMs)` (~43) y `computeBackendKinematics(rms)` (~77); el loop de render
  (`step()` / `requestAnimationFrame`, ~325-370); `setJawTransform` (~307).
- `kateto/core/rms.py`: `map_rms_to_jaw_transform` (~49, espejo Python con los mismos topes),
  `map_rms_to_puppet_transform` (~75).
- `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` y `script/qa/measure_jaw.mjs`.

## Pedido del usuario (textual)
"aumenta más el movimiento del Jaw y además que por cada segundo cambie de rotación y se mueva hacia
allí, por qué está demasiado estático."

Son dos cosas distintas: (A) más recorrido de boca, (B) movimiento **en reposo** (hoy, sin voz, el
avatar queda congelado: no hay ninguna animación idle).

## A. Más recorrido de jaw
- Subí `JAW_MAX_TRAVEL_PX` (32 → **40**) y, si la medición queda corta, bajá un poco más el exponente
  de la curva (`pow(rms, ...)`, hoy ~0.52). Mantené `JAW_MAX_SHAKE_PX` y `HEAD_BOB_PX` proporcionales
  (12 → 16 y 1.8 → 2.6, aprox).
- **No rompas la convención de signos (bugs 112 y 125)**: negativo = la capa de arriba sube = boca
  abierta; silencio = `jawOffsetY` **0 exacto**. La boca cerrada sigue siendo 0.
- Espejá el tope en `kateto/core/rms.py` (los dos paths comparten número).
- Objetivo medido con `script/qa/measure_jaw.mjs` a voz fuerte: subida máxima **≥ 34 px**, promedio
  ≥ 12 px, cruces de nivel medio ≥ 20/s, silencio 0.

## B. Movimiento idle: nueva rotación cada segundo y desplazamiento hacia ahí
Hoy `computeJawKinematics` sólo hace algo si hay RMS: en silencio todo es 0 y por eso se ve estático.

- Constantes nuevas y configurables arriba del archivo: `IDLE_TURN_PERIOD_MS = 1000`,
  `IDLE_TILT_DEG = 8.0`, `IDLE_SWAY_PX = 14.0`, `IDLE_EASE_TAU_MS = 300`, `IDLE_SPEAKING_SCALE = 0.5`.
- Función pura (o clase con estado) tipo `computeIdleMotion(nowMs, rng)`: **cada `IDLE_TURN_PERIOD_MS`
  sortea un objetivo nuevo** — rotación en `±IDLE_TILT_DEG` y desplazamiento lateral en `±IDLE_SWAY_PX`
  **con el mismo signo que la rotación** (así "se mueve hacia donde mira") — y la pose actual se
  **acerca al objetivo con suavizado** (exponencial con `IDLE_EASE_TAU_MS`; tiene que leerse como un
  giro de cabeza, no como un temblor: sin saltos entre frames).
- Se aplica en el **loop de render** (`step()`), sumando a la cinemática de voz:
  `jawRotation = tiltDeVoz + tiltIdle` y `jawOffsetX = shakeDeVoz + swayIdle`.
- **Tiene que correr en los dos modos** (local y backend): es movimiento de render, no depende del RMS.
- Hablando, se escala por `IDLE_SPEAKING_SCALE` (la boca sigue siendo la protagonista); en silencio va
  a plena amplitud y **la boca sigue cerrada** (`jawOffsetY` 0 exacto).
- El azar tiene que ser **inyectable** (rng y reloj) para tests deterministas, como en el intervalo
  aleatorio de visión (fix-112).

## Tests (obligatorios)
En `kateto-avatar.test.mjs` (con rng/reloj sembrados):
- el objetivo **cambia al menos una vez por segundo** (comparando poses en t=0..6s);
- rotación siempre dentro de `±IDLE_TILT_DEG` y sway dentro de `±IDLE_SWAY_PX`, y **mismo signo** entre
  rotación y sway;
- el acercamiento es suave: sin salto mayor a un umbral entre frames (~50 ms) y converge al objetivo
  (sin oscilar de más);
- en silencio `jawOffsetY === 0` **exacto** con el idle andando;
- hablando, el idle aparece escalado (≈ `IDLE_SPEAKING_SCALE`);
- los 9 tests existentes siguen verdes y los tests de overlay en Python (`-k "visual or overlay or rms"`).

## Medición (antes/después, en el resumen y en el bug)
Extendé `script/qa/measure_jaw.mjs` para que además imprima la **serie idle** (rotación y sway
muestreados cada 100 ms durante 6 s, con el objetivo de cada segundo) y la tabla de jaw. Los números van
al resumen del runner.

## Verificación (sin `| tail`, reportá conteos)
1. `node --test kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` (tests/pass/fail)
2. `.venv/bin/python -m pytest kateto/tests/ -q -k "visual or overlay or rms"`
3. `.venv/bin/python -m pytest kateto/tests/ -q` — reportá el baseline que veas (alrededor de
   565 passed / 3 failed preexistentes) y si cambió
4. `git diff --stat`

## Docs
Bug nuevo (id siguiente al más alto que exista: puede haber 126 en curso, usá 127) con el antes/después
y la tabla de la serie idle, + `known-issues.md`.

## Prohibido
- Commitear. Subagentes. Invertir la convención de signos (bug 125). Dejar de cumplir "silencio = boca
  cerrada = 0 exacto" (bug 112). Que el idle necesite voz para andar.
