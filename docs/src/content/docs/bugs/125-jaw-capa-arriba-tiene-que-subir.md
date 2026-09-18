---
id: 125
title: "La capa animada es la de arriba: al hablar tiene que subir, no bajar"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-09-18
---

## 125. La capa animada es la de arriba: al hablar tiene que subir, no bajar

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`

### Descripción

Reportado por usuario (textual): "Además el Jaw se mueve hacia abajo y no hacia
arriba y más alto como debería."

### Evidencia (verificada mirando los assets, no leyendo código)

Las dos capas del avatar son:

- `avatar_jaw.png` — el `.layer-jaw` **que se anima** (`z-index: 1`, detrás): es la
  parte **de ARRIBA** de la cabeza (pelo, frente, cejas, ojos, nariz, boca con
  dientes). Corte horizontal a la altura de la boca. Verificado con visión sobre
  Jane (498 KB) **y** doktor (650 KB).
- `avatar_head.png` — el `.layer-head` (`z-index: 2`, delante): es la parte
  **de ABAJO** (labios, mentón, barba, cuello, torso). Corte a la altura de la boca.

O sea: **la capa que se mueve es la de arriba**. Con la convención anterior
(`jawOffsetY` positivo = `translateY(+)` = hacia abajo) la pieza de arriba
**bajaba** al hablar: se superponía sobre la de abajo y la boca se cerraba/hundía
en vez de abrirse. Abrir la boca = **esa capa sube** (aparece la luz entre las dos
piezas, estilo Muppet).

### Medición (protocolo: silencio 0.3 s / habla 1.5 s rms 0.2-0.5-0.8 / silencio 0.4 s @60 Hz)

Script: `script/qa/measure_jaw.mjs` (path local; backend sin flap como referencia de topes).

| Métrica (habla) | Antes (bug 122) | Después |
|---|---|---|
| `jawOffsetY` local min / max | 0 / +28.43 | **-28.43** / 0 (sube) |
| `jawOffsetY` local mean | +9.62 | **-9.62** (\|media\| ≥ 9 ✓) |
| negativos / positivos / ceros (local) | 0 / 85 / 5 | **85 / 0 / 5** |
| `jawOffsetY` backend min / max | +5.05 / +25.26 | **-25.26** / -5.05 |
| `jawOffsetY` backend mean | +15.16 | **-15.16** |
| cruces de nivel medio (1.5 s habla) | 33 (~22/s) | 33 (~22/s, ≥ 20/s ✓, física intacta) |
| retornos al neutro exacto (local) | 5 | 5 |
| silencio inicial/final en 0 exacto | sí / sí | sí / sí |
| `headOffsetY` backend (rms 0.5 / 1.0) | -0.85 / -1.80 (subía = cerraba) | **+0.85 / +1.80** (baja = ayuda a abrir) |
| salto máx. local vs backend | 25.26 | 25.26 (flap vs sin flap, sin inversión de signo) |

Voz fuerte (rms → 1.0): local pica -32 (tope teórico), medido -28.43 con rms 0.8;
recorrido hacia arriba ~28-32 px ✓. Contenedor `:host`/`.container` ya con
`overflow: visible`: la subida no se recorta con el tope de 32.

### Impacto

La boca se abría al revés (la pieza de arriba bajaba y tapaba la boca); ahora la
capa de arriba sube al hablar y la pieza de abajo baja levemente para ayudar.

### Causa

La convención de signos de los bugs 112/122 ("positivo = mandíbula baja = boca
abierta") asumía que la capa animada era la mandíbula inferior. Con estos assets
la capa animada es la mitad **superior**, así que el signo quedó al revés. El
`head bob` (`-factor * HEAD_BOB_PX`, hacia arriba) también cerraba la boca con la
nueva geometría.

### Solución aplicada

- `computeJawKinematics`: signo en un solo lugar —
  `openMovement = -(factor * JAW_MAX_TRAVEL_PX * shapedFlap)`. Tope 32 intacto.
- `computeBackendKinematics`: `jawOffsetY = -(factor * JAW_MAX_TRAVEL_PX)`,
  `headOffsetY = +(factor * HEAD_BOB_PX)` (baja, ayuda a abrir). Tilt sin invertir
  (simétrico alrededor del pivote, se lee como boca).
- `kateto/core/rms.py` (`map_rms_to_jaw_transform` / `map_rms_to_puppet_transform`):
  mismo signo — jaw negativo, head positivo — para que los dos paths coincidan.
- Comentarios `SHARED CONVENTION` reescritos (bugs 112+125): negativo = sube = abre,
  con aviso explícito de no volver a invertirlo. `setJawTransform` usa `Math.abs`,
  así que el fallback (`mouth.png`/`top.png`) no se toca. `index.html`/`courtroom.html`
  animan vía `setRms`, así que el cambio propaga solo.
- Tests invertidos en `kateto-avatar.test.mjs` (hablando ⇒ `jawOffsetY ≤ 0`,
  "más energía ⇒ más subida", head `≥ 0`) y en `kateto/tests/test_visual_overlay.py`
  (mapping `-16.0`, passthrough `-16.0`, convención compartida `≤ 0`/`≥ 0`).

**Tests:** `node --test kateto-avatar.test.mjs` 9/9 ✓ ·
`pytest -k "visual or overlay or rms"` 14 passed ✓ ·
suite completa 557 passed / 3 failed (preexistentes, verificados en árbol pristino).

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/core/rms.py`, `kateto/tests/test_visual_overlay.py`, `script/qa/measure_jaw.mjs`, `docs/src/content/docs/runtime/overlay.md`
