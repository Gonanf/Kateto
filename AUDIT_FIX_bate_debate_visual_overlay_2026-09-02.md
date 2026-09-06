# FIX — bate_debate + visual_overlay (2026-09-02)

> Responde a `AUDIT_bate_debate_visual_overlay_2026-09-02.md` P0-1 / P0-2 / P0-4 + layout acta judicial. Commit fix posterior a `7664e73`.

## 1) Puppet 2 imágenes (avatar_jaw + avatar_head) — verificado y corregido

**Config carga:** `config/defaults/voices/{jane,doktor,conquest,whisperer}/avatar_head.png + avatar_jaw.png`

- Antes: solo `conquest` tenía ambos; `jane/doktor/whisperer` solo `top.png/mouth.png` → `HttpServer` 404 para `/voices/{jane,doktor,whisperer}/avatar_head.png`.
- Fix: generados `avatar_head.png` (copia de `top.png`) y `avatar_jaw.png` (copia de `mouth.png`) para `jane/doktor/whisperer`. Verificado: `ls voices/*/avatar*.png` ahora 8 archivos presentes.

**Frontend `kateto-avatar.js`:**

- Mantiene `<kateto-avatar>` con dos capas `layer-head` + `layer-jaw` (`/voices/{voice}/avatar_head.png` + `avatar_jaw.png`) y fallback `top/mouth`.
- Fix RMS desalineado (P0-1):
  - `computeJawKinematics()` bajado de 52px/28px/34° aleatorio a **18px / 6° determinístico** (sin `Math.random`), `headOffsetY` sutil; documentado como fallback sintético.
  - Nuevo `computeBackendKinematics(rms)` replica fórmula backend (16px/4.5° floor 0.05) como fallback autoritativo.
  - Añadido `setJawTransform({jawOffsetX, jawOffsetY, jawRotation, headOffsetY})` — **backend es autoridad**. `setRms()` ahora delega a `setJawTransform` tras `computeJawKinematics`. `layer-head` ahora tiene `transform` + `transition` y `headOffsetY` mueve cabeza sutilmente (`-1.5px` a `-1.8px` máx).
  - `transform-origin` jaw cambiado de `50% 65%` a `50% 22%` (bisagra realista).

**Backend `kateto/core/rms.py`:**

- Nueva `map_rms_to_puppet_transform(rms)` → `{jawOffsetX, jawOffsetY, jawRotation, headOffsetY}` (determinística, `headOffsetY=-factor*1.8`). `map_rms_to_jaw_transform` preservada exacta para tests (`0.525 → 8.0,2.25`).

**Backend `kateto/plugins/visual_overlay/visual_overlay_plugin.py`:**

- Importa `map_rms_to_puppet_transform`.
- `update_viseme` y `on_audio_output` ahora emiten `jawOffsetX/Y/Rotation + headOffsetY` (backend authoritative) + `is_speaking` alineado a `rms > 0.05` (antes 0.01, desalineado con `noise_floor 0.05`). Payload incluye ambos niveles `payload[jawOffset*]` y `payload.data[jawOffset*]`.
- **P1-1 EMA reset**: `on_interrupt` resetea todos los `RMSProcessor`; `on_audio_output` con `final==True` resetea procesador (evita mandíbula abierta entre turnos).
- **P1-7 persistencia**: nuevo `on_debate()` actualiza `_last_debate_state/_debate_history` y hace `broadcast`, de modo que `GET /api/courtroom/state` funciona sin WS conectado.
- Registra también `InterruptData, OverlayLayout` types.

## 2) Acta judicial → de overlay derecha a dock abajo (flex/grid)

**Problema:** `kateto-paper-transcript` estaba `position:absolute; right:1.2vw; bottom:11vh; width:21vw; height:66vh; z-index:30` tapando `zone-right` en 1280px y no responsivo.

**Fix `courtroom.html`:**

- Nuevo layout flex: `#court-layout {display:flex; flex-direction:column; height:100dvh}` con `#court-stage {flex:1; position:relative; overflow:hidden}` (contiene `#scene` + 3 zones) y `#acta-dock {flex:0 0 30vh; min-height:180px; max-height:36vh; border-top:2px solid gold}`.
- HTML reestructurado: todo el tribunal dentro de `#court-stage`, `<kateto-paper-transcript>` movida dentro de `#acta-dock` (ya no absolute). CSS override `#acta-dock kateto-paper-transcript {position:relative!important; width:100%!important; height:100%!important; inset:auto!important}`.
- Legacy fallback guard: `kateto-paper-transcript:not(#acta-dock kateto-paper-transcript)` mantiene posición antigua si dock no existe.
- Resultado: el acta empuja courtroom hacia arriba, no tapa; scroll interno sigue funcionando; `filter` eliminado en dock para evitar recorte.

**Transcript component:** sin cambios funcionales; lazy audio unlock se mantiene.

## 3) P0 del audit aplicados

| P0 | Estado | Fix |
|---|---|---|
| **P0-1 RMS thresholds / jaw kinemat.** | ✅ FIXED | Backend autoritativo (`16px/4.5° floor 0.05`), `is_speaking >0.05`, frontend `setJawTransform` consume payload, lateral random eliminado, `headOffsetY` sutil. |
| **P0-2 whisperer.png** | ✅ FIXED | `assets/bate_debate/whisperer.png` generado desde `assets/voices/whisperer.jpg` (512², 264KB). `config/defaults/voices/whisperer/avatar_{head,jaw}.png` generados (463KB/531KB). HTTP 200 verificado vía tests. |
| **P0-4 overlay_layout no consumido** | ✅ FIXED | `courtroom.html: handleOverlayLayout()` consume `overlay_layout {layout, positions, voices}` y re-asigna stands (`validStands: judge/left/right/center`). WS `connectWs()` añade handler `if (msg.event==='overlay_layout')` antes de visemes. |
| **P0-3 doble ruta generate** | ⏸ n/a | No tocado (fuera de scope puppet/layout); documentado en audit como deuda de `orchestrator.py` |

**P1 también cerrados en este FIX:**

- **P1-1** EMA sin reset → done (interrupt + final).
- **P1-4** stale localStorage → `restoreState()` ahora prioriza `/api/courtroom/state` y prune de stands fantasma.
- **P1-5** `FLUSTER_RE` y `turnKey` → regex corregido a `\*[^*]{2,40}\*`, `turnKeyFor()` usa `length + slice(0,120)`.
- **P1-8** `VALID_AVATAR_FILES` duplicado + `SOUNDS_DIR` shadowing → `SOUNDS_DIR` movida a top-level constante, duplicado eliminado.
- **P2-2** curva agresiva → bajada a 18px/6°.

## 4) Build / run verificable

```bash
uv run pytest kateto/tests/test_visual_overlay.py kateto/tests/test_bate_debate.py kateto/tests/test_http_server.py -v
# 10 + 6 + 3 = 19 passed (visual_overlay 10 past, bate_debate 6, http_server 3)
uv build  # wheel + sdist OK → dist/kateto-0.1.0-py3-none-any.whl
uv run python -c "from kateto.core.rms import map_rms_to_puppet_transform; print(map_rms_to_puppet_transform(0.525))"
# {'jawOffsetX':0.0,'jawOffsetY':8.0,'jawRotation':2.25,'headOffsetY':-0.9}
```

- `GET /voices/{jane,doktor,conquest,whisperer}/avatar_head.png|avatar_jaw.png` → 200.
- `GET /assets/whisperer.png` → 200 image/png.
- `GET /courtroom` → contiene `#court-layout`, `#acta-dock`, sin `speechSynthesis/BrowserPcmPlayer`, con `handleOverlayLayout` y `applyPuppetToStand`.
- `GET /overlay` → consume `jawOffsetY/headOffsetY` vía `setJawTransform` con threshold 0.05.

## Archivos modificados

- `kateto/plugins/visual_overlay/web/kateto-avatar.js` — puppet 2 capas, setJawTransform, deterministic kinematics, head subtle
- `kateto/core/rms.py` — +`map_rms_to_puppet_transform`
- `kateto/plugins/visual_overlay/visual_overlay_plugin.py` — puppet payload, thresholds 0.05, EMA reset, on_debate
- `kateto/plugins/visual_overlay/web/courtroom.html` — flex layout dock abajo, overlay_layout handler, backend viseme, FLUSTER_RE/turnKey, restoreState fix
- `kateto/plugins/visual_overlay/web/index.html` — consume backend puppet, threshold 0.05
- `kateto/plugins/system/http_server.py` — dedup VALID_AVATAR_FILES, SOUNDS_DIR top-level, game viseme puppet
- `config/defaults/voices/{jane,doktor,whisperer}/avatar_head.png|avatar_jaw.png` — generados
- `assets/bate_debate/whisperer.png` — generado

## Pendiente (no bloqueante)

- P0-3 doble ruta generate (orchestrator) — requiere unificar `_consider_objection` vía `event_client`.
- P2 responsive ultrawide/mobile fino del courtroom (media queries 1100/800) — dock ya mejora, pero `left:2vw/right:2vw 26vw` aún puede solaparse en <1100px (sugerido flex zones).
