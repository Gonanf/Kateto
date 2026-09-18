---
id: 112
title: "Jaw del overlay sólo se mueve hacia arriba (no hay ciclo abre/cierra)"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-09-18
---

## 112. Jaw del overlay sólo se mueve hacia arriba (no hay ciclo abre/cierra)

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`

### Descripción

Reportado en vivo: la animación de jaw en el visual overlay sólo se movía hacia arriba,
sin el movimiento de arriba y abajo que simula una boca hablando. Causa confirmada por
medición (no asumida): `computeJawKinematics` calculaba
`upMovement = -((6.0 + 40.0 * flap) * (0.5 + 0.5 * factor))` — `6.0 + 40.0 * flap`
siempre positivo con el signo pegado afuera, así que `jawOffsetY` nunca era ≥ 0:
desplazamiento permanente hacia arriba con wobble, sin volver al neutro. Además
convivía con el path del backend (`computeBackendKinematics` / `map_rms_to_puppet_transform`,
`kateto/core/rms.py:78`) que usa la convención opuesta (positivo, 0..16), con saltos
de hasta ~55 px al alternar entre paths.

### Medición (protocolo: silencio 0.3 s / habla 1.5 s rms 0.2-0.5-0.8 / silencio 0.4 s @60 Hz)

Script: `script/qa/measure_jaw.mjs` (corre sobre el JS real; validado con números
idénticos en Chromium headless vía harness temporal + `http.server`).

| Métrica (habla, path local) | Antes | Después |
|---|---|---|
| min `jawOffsetY` | -42.64 | 0.02 (≈ 0, vuelve al neutro) |
| max `jawOffsetY` | -4.61 | 13.69 (> 0, abre) |
| mean `jawOffsetY` | -20.78 | 4.79 |
| signo dominante | 90/90 negativo | 90/90 positivo (misma convención que backend) |
| cruces del nivel medio (2 por ciclo abre/cierra) | 0 | 24 en 1 s |
| salto máx. local vs backend (mismo rms) | 55.27 px | 11.65 px (resta solo la fase del flap, sin inversión de signo) |
| silencio inicial/final en 0 | sí / sí | sí / sí |

### Impacto

La boca se veía "pegada arriba" vibrando en vez de abrir/cerrar; al alternar entre
`setRms` (local) y `setJawTransform` (backend) el jaw saltaba entre convenciones opuestas.

### Causa

Piso constante de 6 px + signo negativo fijo en `computeJawKinematics`: la amplitud no
escalaba a 0 con el silencio y el flap se sumaba a un offset en vez de multiplicar la
amplitud. Tilt lateral absurdo de hasta ±40° en la misma función.

### Solución aplicada

Convención única: positivo = abre, neutro 0 = cerrada. `jawOffsetY = factor * 16.0 * flap`
(el flap multiplica la amplitud, sin piso; `factor → 0` en silencio). Recorrido máximo
en un solo lugar (`JAW_MAX_TRAVEL_PX = 16.0`, mismo que el backend). Tilt acotado a ±4.5°
(igual que el backend). `computeBackendKinematics` reescrito sobre las mismas constantes,
sin cambio de comportamiento. Las curvas de `factor` no se unificaron a propósito: la
local es punchy (exponente 0.68, umbral 0.015) para TTS sintético con rms bajos de
`pulseWord`; la del backend es lineal (umbral 0.05) para RMS real. El cierre al final del
turno ya llegaba al overlay (el plugin resetea la EMA en `on_interrupt`/`on_audio_output`
con `final` y el front cierra con `setRms(0)` / `setJawTransform({...0})`); con el fix ese
0 es de verdad el neutro en ambos paths.

**Tests:** `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` (7 asserts vía
`node --test`: min ≈ 0, max > 0, ≥ 4 cruces, tope 16 px, tilt ≤ 4.5°, silencio exacto) +
2 wrappers en `kateto/tests/test_visual_overlay.py` (suite JS y paridad JS-backend vs
`map_rms_to_puppet_transform`, skip sin node). Ningún test existente afirmaba la
convención vieja del JS (los de Python ya esperaban positivo), así que no hubo que
actualizar ninguno.

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/tests/test_visual_overlay.py`, `script/qa/measure_jaw.mjs`
