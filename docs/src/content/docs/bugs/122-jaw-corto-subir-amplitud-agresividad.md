---
id: 122
title: "Jaw del overlay quedó corto tras la corrección de dirección: subir amplitud y agresividad"
severity: Media
status: resolved
component: kateto/plugins/visual_overlay/web/kateto-avatar.js
resolved: 2026-09-18
---

## 122. Jaw del overlay quedó corto tras la corrección de dirección: subir amplitud y agresividad

**Severidad:** Media
**Componente:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`

### Descripción

Reportado por usuario (textual): "El movimiento de Jaw es muy poco, debe ser más alto y más
agresivo." Tras el bug 112 el jaw abría en la dirección correcta pero con recorrido promedio de
~4.8 px sobre un tope teórico de 16 px: se veía poco y sin punch.

### Medición (protocolo: silencio 0.3 s / habla 1.5 s rms 0.2-0.5-0.8 / silencio 0.4 s @60 Hz)

Script: `script/qa/measure_jaw.mjs` (path local; backend sin flap como referencia de topes).

| Métrica (habla, path local) | Antes (bug 112) | Después |
|---|---|---|
| min `jawOffsetY` | 0.02 (≈ 0) | 0 (exacto, vuelve al neutro 5 veces) |
| max `jawOffsetY` | 13.69 | 28.43 (tope teórico 32) |
| mean `jawOffsetY` | 4.79 | 9.62 |
| positivos / ceros exactos | 90 / 0 | 85 / 5 |
| cruces del nivel medio en 1 s (2 por ciclo) | ~16 (8 Hz) | 22 (9 Hz) |
| silencio inicial/final en 0 | sí / sí | sí / sí |
| tilt máx. medido | ±4.5° | ±6.15° (tope 6.5°) |
| shake máx. medido | ±9 px | ±11.35 px (tope 12 px) |

Escala con energía (picos medidos a 60 Hz): rms 0.1 → 8.95 px, 0.2 → 13.41 px,
0.5 → 22.14 px, 0.8 → 28.44 px. El salto máx. local vs backend sube de 11.65 a
25.26 px: esperable (más amplitud + flap afilado contra backend sin flap), sin
inversión de signo en ningún rms.

### Impacto

La boca apenas se movía en el overlay; ahora abre ~28 px con ataque marcado.

### Causa

Tope bajo (16 px) + curva de energía conservadora (exponente 0.68) + flap
sinusoidal puro: la media quedaba en ~4.8 px y el pico rara vez se sostenía.

### Solución aplicada

- `JAW_MAX_TRAVEL_PX` 16.0 → 32.0, `JAW_MAX_TILT_DEG` 4.5 → 6.5,
  `JAW_MAX_SHAKE_PX` 12.0 (antes 9.0 inline), `FLAP_HZ` 8 → 9.
- Curva de energía más punchy: exponente 0.68 → 0.52 (responde fuerte con poca voz).
- Flap con ataque afilado: `shapedFlap = flap^1.25` (cierra más tiempo, abre con
  más punch); sigue multiplicando 0..1, sin piso fijo, y vuelve a 0 exacto.
- Gate de silencio intacto (`rms < 0.015` → 0 exacto) y shake sólo en `jawOffsetX`
  (el personaje entero no se mueve).
- `computeBackendKinematics` hereda los mismos topes vía constantes; `kateto/core/rms.py`
  (`map_rms_to_jaw_transform` / `map_rms_to_puppet_transform`) actualiza sus defaults
  16.0/4.5 → 32.0/6.5 para mantener la paridad JS↔Python (todos los callers usan defaults).

**Tests:** `kateto-avatar.test.mjs` (9 asserts vía `node --test`: umbrales actualizados
a max > 20, tope 32 px, tilt ≤ 6.5°, más 2 nuevos: "más energía ⇒ más recorrido" y
"silencio ⇒ 0 exacto") + `kateto/tests/test_visual_overlay.py` (topes 32.0/6.5 en mapping
puro y passthrough). Suite overlay/avatar verde.

**Archivos:** `kateto/plugins/visual_overlay/web/kateto-avatar.js`, `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`, `kateto/core/rms.py`, `kateto/tests/test_visual_overlay.py`, `script/qa/measure_jaw.mjs`
