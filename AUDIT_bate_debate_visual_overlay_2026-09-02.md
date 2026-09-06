# Audit — bate_debate + visual_overlay (avatar_head/jaw · RMS · visemes · overlay_layout)

> Solo audit. Sin cambios de código. Fecha 2026-09-02. Commit base `7664e73` (feat debate/courtroom). Workspace `~/proyectos/OpenaiBuildWeek/Kateto/`.

---

## Resumen ejecutivo

El sistema está funcional y testeado (mock flow completo), pero hay **desalineaciones críticas** entre el pipeline RMS/visemes backend (`core/rms.py` + `visual_overlay_plugin.py`) y el frontend puppet (`kateto-avatar.js` + `courtroom.html`), un `overlay_layout` que no llega al courtroom, y lógica de debate con 2 rutas de generación inconsistentes. La mejora visual puppet (muppet cutout) está integrada pero compite con valores RMS del backend que el courtroom ignora.

**Prioridad sugerida:** corregir primero lo que rompe sincronía audio↔mandíbula y lo que deja a `whisperer` sin asset; luego cerrar debt de courtroom layout y registry; por último pulir estética.

---

## 1. Flujo real verificado (para entender el audit)

### 1.1 bate_debate (`kateto/plugins/bate_debate/orchestrator.py`, 922 L)

```
run_debate() → _AsyncDebate.run_one(topic) →
  a) _judge_propose_topic()  [phase=opening,  PH /tmp/kateto_opening.wav]
  b) loop debaters × rounds → _argument() [phase=argument]
        ↳ 50% rng → _consider_objection() [phase=objection] SI → cue 70% + interrupt + _rebuttal() [phase=rebuttal]
     fallback (sin objeción) → _objection() + _rebuttal() garantizados
  d) _ruling()  [phase=ruling] + _parse_rulings()
  e) _verdict() [phase=verdict]
  → _write_registry() (.md + .jsonl)
  → on_speak(voice_id, role, phase, text) por cada turn (incl. thinking con text="")
  → _wait_for_speech_finish() espera TTS player idle + delay
```

Fase codificada en `reference_wav = /tmp/kateto_{phase}.wav` (`_speak()` L258). `mock.py` detecta fase vía `reference_wav.stem` (`_detect_phase()` L54) — robusto.

### 1.2 visual_overlay

* **Plugin** `kateto/plugins/visual_overlay/visual_overlay_plugin.py` (197 L):
  `on_text_chunk` → broadcast `{event:text_chunk, type:subtitle}`,
  `on_audio_output` → `compute_rms()` → `map_rms_to_jaw_transform()` → broadcast `{event:audio_output, type:viseme, rms, jawOffsetY, jawRotation, audio(b64), is_speaking}`,
  `on_overlay_layout` → broadcast `{event:overlay_layout}`,
  `on_interrupt` → broadcast `{event:interrupt}`.
  Mantiene `_last_debate_state` / `_debate_history` solo vía `visual_overlay_plugin.py` L32-33 (vacío de inicio).

* **HTTP** `kateto/plugins/system/http_server.py` (453 L):
  `GET /overlay` → `visual_overlay/web/index.html`,
  `GET /courtroom` → `visual_overlay/web/courtroom.html`,
  `GET /components/{file}` → `visual_overlay/web/*`,
  `GET /voices/{name}/{file}` → `voices/{name}/{avatar_head.png,avatar_jaw.png,top.png,mouth.png}`,
  `GET /assets/{file}` → `assets/bate_debate/*`,
  `WS /ws/overlay` → relay fan-out + persiste `plugin._last_debate_state`/`_debate_history` si `event==debate` (L347-353),
  `GET /api/courtroom/state` → lee `plugin._last_debate_state`.

* **CLI** `kateto/cli/commands.py:Debate` (L279-417) + `_make_overlay_broadcaster()` (L461-622):
  `on_speak` → `app.stdout` + `_Broadcaster()(voice_id, role, phase, text)` vía thread+event_loop dedicado que reconecta WS.

* **Frontend puppet** `visual_overlay/web/kateto-avatar.js` (21 897 B):
  `computeJawKinematics(rms)` (L14), `<kateto-avatar>` head+jaw layers + fallback `top.png`/`mouth.png` (L109), `pulseWord()` para TTS sintético, `SubtitleStreamer` + `<kateto-subtitles>`.

* **Frontend courtroom** `visual_overlay/web/courtroom.html` (631 L):
  CSS zones `#zone-judge/left/right/center` + furniture `judge_bench.jpg/stand_left/right.jpg` + bg `courtroom_bg.jpg` + `<kateto-paper-transcript>` (typewriter clicks). JS `assignStand()`, `activateStand()`, `popObjection()`, `handleDebate(msg)`, WS `connectWs()` → consume `audio_output/viseme` para `setRms()` + `debate` para transcript.

* **RMS backend** `kateto/core/rms.py` (122 L):
  `calculate_raw_rms` → `normalize_rms` (thresholds 0.01/0.8) → `apply_ema(alpha 0.3)` → `map_rms_to_jaw_transform` (threshold 0.05, 16 px / 4.5°).

---

## 2. Hallazgos priorizados

### P0 — Roto o desalineado (corregir antes de pulir estética)

#### P0-1 Desalineación RMS/kinematics backend ↔ frontend
- **Archivos:** `kateto/core/rms.py:49-70`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py:127,155`, `kateto/plugins/visual_overlay/web/kateto-avatar.js:14-34,240-251`, `kateto/plugins/visual_overlay/web/courtroom.html:589-598`
- **Qué pasa:** El plugin envía `jawOffsetY/rotation` calculados con `map_rms_to_jaw_transform` (lineal, 0.05 floor, 16 px/4.5°). El courtroom **ignora** esos campos y recalcula vía `computeJawKinematics(rms)` (exponencial `pow 0.68`, floor 0.015, picos 52 px + 28 px lateral + 34° tilt con `Math.random()` por frame). `index.html` vía `BrowserPcmPlayer` también tiene su propia curva. Resultado: el mismo `rms=0.6` produce bocas distintas según ruta; valores del payload nunca se usan en courtroom.
- **Síntoma:** Mandíbula temblor lateral aleatorio en cada frame (sideShake con `Math.random()` sin seed), no sincronizado con RMS real;diff de umbrales (`0.05` vs `0.015` vs `0.01` en `is_speaking`) hace que `zone.talking` parpadee.
- **Fix:** Elegir una sola fuente de verdad. Opción A (recomendada): que el backend sea autoritativo — courtroom aplique directamente `msg.jawOffsetY/Rotation` + `jawOffsetX` si se añade, y `kateto-avatar.js:setRms()` deje de recalcular. Opción B: unificar fórmula en `rms.py` y `kateto-avatar.js` y que `setRms(rms)` sea el único cálculo. En cualquiera, alinear thresholds (`noise_floor`, `0.015`, `0.01`).
- **Esfuerzo:** M

#### P0-2 Avatar `whisperer` sin assets (puppet roto en tribunal)
- **Archivos:** `assets/bate_debate/` (solo `jane.png/doktor.png/conquest.png`), `kateto/plugins/system/http_server.py:24`, `kateto/plugins/visual_overlay/web/kateto-avatar.js:237-238`, `kateto/plugins/visual_overlay/web/courtroom.html:306-332`
- **Qué pasa:** `whisperer` es debater por defecto (`commands.py:287`) y está en `MockProvider`/`_PROFILES`, pero no hay `assets/bate_debate/whisperer.png` ni se prescribe `voices/whisperer/avatar_head.png|avatar_jaw.png`. `_enableFallback()` cae a `top.png`/`mouth.png`; si tampoco existen, queda hueco vacío en `zone-left/right`. El test `test_visual_overlay` crea dummy, en prod no hay.
- **Fix:** Añadir `assets/bate_debate/whisperer.png` y documentar/validar `voices/{voice}/avatar_{head,jaw}.png` para los 4 voices; añadir fallback placeholder (silueta o inicial) y warning en `http_server:voice_asset` cuando falta.
- **Esfuerzo:** S (asset + 404 handler)

#### P0-3 Doble ruta de generación: `EventDebateClient` vs `provider_factory` directo
- **Archivos:** `kateto/plugins/bate_debate/orchestrator.py:185-232,356-379,470-506,508-523`
- **Qué pasa:** `_speak_turn()` usa `event_client.generate_turn()` si hay `manager` (va por bus/voice plugin/turn gate). `_consider_objection()` (L488-496) y el fallback `_objection()` (L517) llaman directo a `provider_factory(raiser)` + `_speak()` **ignorando** el manager aunque exista. Resultado: objeciones no respetan `voice_idle`/`_wait_for_speech_finish`, no pasan por `TurnGate`, y pueden solaparse con el audio del argumento aún sonando.
- **Fix:** Unificar: que `_consider_objection`/`_objection` pasen por `_speak_turn()` (o por `event_client` con `phase=objection`). Si se quiere heurística rápida, al menos documentar y testear carrera.
- **Esfuerzo:** S

#### P0-4 `courtroom.html` no consume `overlay_layout` (layout de juegos no llega al tribunal)
- **Archivos:** `kateto/plugins/visual_overlay/visual_overlay_plugin.py:100-113`, `kateto/plugins/visual_overlay/web/index.html:565`, `kateto/plugins/visual_overlay/web/courtroom.html:544-605`
- **Qué pasa:** `index.html` maneja `msg.event==='overlay_layout'` y reposiciona cards. `courtroom.html` solo maneja `audio_output|interrupt|debate`; ignora `overlay_layout`. Si `game_bridge` o CLI emite `OverlayLayout(layout=sides, positions={...})` el tribunal no se mueve.
- **Fix:** Añadir handler `overlay_layout` en `courtroom.html:connectWs()` que remapee `standByVoice` y haga `transition` de zones (reusar `L659` lógica de `index.html`).
- **Esfuerzo:** S

### P1 — Bugs / debt funcional (afecta estabilidad o UX)

#### P1-1 EMA sin reset → mandíbula queda abierta entre turnos
- **Archivos:** `kateto/core/rms.py:73-122`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py:50-62,148-189`, `kateto/plugins/audio_output/*:wait_idle`
- **Qué pasa:** `RMSProcessor._current_ema` nunca se resetea al final de turno ni en `on_interrupt`. Tras hablar, el EMA decae lentamente y el siguiente `compute_rms` arranca con residuo. Si el chunk siguiente es silencio corto, `is_speaking=rms>0.01 && !final` puede seguir true.
- **Fix:** `on_audio_output` si `data.final` → `processor.reset()`; `on_interrupt` → reset todos los `RMSProcessor`; exponer `VisualOverlayPlugin.reset_visemes()`. Añadir `processor.reset()` en `courtroom.html` handler de `interrupt`.
- **Esfuerzo:** S

#### P1-2 `_wait_for_speech_finish` no espera sin manager (mock/CLI directo)
- **Archivos:** `kateto/plugins/bate_debate/orchestrator.py:386-411`
- **Qué pasa:** `if delay==0 and manager is None: return` (L387). En `run_debate(..., manager=None, delay=0)` (caso `--self-test`/`--mock`) no hay espera; los `on_speak` typewriter se encolan sin pacing y el registry escribe inmediato. En modo real con `manager=None` + provider directo (fallback de `commands.py:376`) tampoco espera y se pisa TTS siguiente.
- **Fix:** Mantener al menos `await asyncio.sleep(est_duration)` aunque no haya manager, o documentar que `delay=0` solo vale para tests.
- **Esfuerzo:** XS

#### P1-3 Polling de `player._playing` frágil
- **Archivos:** `kateto/plugins/bate_debate/orchestrator.py:643-648`, `kateto/plugins/audio_output/player.py`, `edgetts.py:46`, `boson_tts_plugin.py:54`
- **Qué pasa:** Accede a atributo privado `_playing` que no es contrato (`player.py` usa cola, `edgetts/boson` usan `_set_playing`). Si player no expone `_playing` (o renombra), el `while` espera `cue_duration` completo siempre; si sí existe, puede hacer busy-wait 20 Hz.
- **Fix:** Usar contrato `player.wait_idle(timeout)` como en `_wait_for_speech_finish` (L398/403) o añadir `player.is_playing()` público.
- **Esfuerzo:** S

#### P1-4 Persistencia de stands con `localStorage` stale
- **Archivos:** `kateto/plugins/visual_overlay/web/courtroom.html:354-405,412-442`
- **Qué pasa:** `standByVoice` y `kateto_courtroom_state` se guardan en localStorage y `restoreState()` los rehidrata sin validar voces actuales. Si se cambia `--voices whisperer,doktor` → `--voices conquest,doktor`, quedan stands fantasma. Además `restoreState` usa `role===judge?orchestrator:adversary` fijo (L416) ignorando `role` real.
- **Fix:** Invalidar localStorage si `Object.keys(standByVoice)` no coincide con `current.debaters+judge`; guardar `version`/`topic` y limpiar en cambio. En `restoreState`, persistir `role` junto a `stand`.
- **Esfuerzo:** S

#### P1-5 Dedup `seenTurns` por prefijo 60 chars colisiona + `FLUSTER_RE` inválida
- **Archivos:** `kateto/plugins/visual_overlay/web/courtroom.html:457,475`
- **Qué pasa:** `turnKey = voiceId+phase+text.slice(0,60)` — dos argumentos distintos con mismo opening se descartan. `FLUSTER_RE = /(\*[^^*]{2,40}\*|...)` — `^^*` es `[^ ^*]` mal escapado; debería ser `[^*]`. No afecta grave pero impide detectar `*golpea la mesa*` con doble asterisco.
- **Fix:** `turnKey` con hash completo o `text.slice(0,120)` + length; corregir regex a `/\*[^*]{2,40}\*/`.
- **Esfuerzo:** XS

#### P1-6 `_parse_rulings` frágil + `registry` colisión de nombres y falta de lock
- **Archivos:** `kateto/plugins/bate_debate/orchestrator.py:568-578,830-921`
- **Qué pasa:** Regex ` (ACEPTADA|DENEGADA)\s*[:-]?\s*([^.]*(?:\.(?!\s*(?:OBJECION|ACEPTADA|DENEGADA))[^.]*)*\.?)` corta razonamiento en el primer punto que no sea seguido de OBJECION; si la jueza escribe dos oraciones, se pierde la segunda. `_write_registry` usa `stamp` con segundos + `slugify(topic)`; en modo `infinite` con `max_debates>1` y mismo topic puede colisionar. `jsonl_path.open("a")` sin lock; dos procesos CLI concurrentes corrompen línea.
- **Fix:** Parser más laxo: capturar hasta siguiente `OBJECION N:` o fin de string; `md_path` con `stamp + uuid4 hex4` o `count`; envolver jsonl con `filelock` o retry.
- **Esfuerzo:** S

#### P1-7 `visual_overlay_plugin.py` — `_last_debate_state` solo vía WS relay (no vía bus)
- **Archivos:** `kateto/plugins/visual_overlay/visual_overlay_plugin.py:32,64-73`, `kateto/plugins/system/http_server.py:242-248,328-373`
- **Qué pasa:** `GET /api/courtroom/state` lee `plugin._last_debate_state`, pero ese campo solo se escribe en `http_server.py:348` dentro de `WS /ws/overlay` cuando entra un msg `event==debate`. Si el overlay no está conectado (o se cae), el campo queda `None` aunque el debate haya emitido `on_speak` vía bus. Debería haber `on_debate` en el plugin o `manager.emit("debate", ...)` que el plugin escuche.
- **Fix:** Añadir `async def on_debate(self, data)` en `VisualOverlayPlugin` que actualice `_last/_history` y haga `broadcast`; hacer que `on_speak` del CLI emita también `debate` al bus cuando hay `manager`.
- **Esfuerzo:** S

#### P1-8 `VALID_AVATAR_FILES` duplicado + `SOUNDS_DIR` dentro de función (shadowing)
- **Archivos:** `kateto/plugins/system/http_server.py:24-26,205`
- **Qué pasa:** Línea 24 y 26 definen `VALID_AVATAR_FILES` idéntico (copypaste). `SOUNDS_DIR` global no existe, se redefine dentro de `courtroom()` closure (L205) — funciona pero confuso y no testeado fuera.
- **Fix:** Eliminar duplicado, mover `SOUNDS_DIR`/`ASSETS_DIR` a top-level constantes.
- **Esfuerzo:** XS

#### P1-9 WS relay de audio_input y game bridge ruidoso + polling `get_event_loop().create_task` deprecated
- **Archivos:** `kateto/plugins/system/http_server.py:383-413,392-410`
- **Qué pasa:** `_on_event` parsea cada `text_chunk` con `re.findall(r"[a-h][1-8][a-h][1-8][qrbn]?")` para detectar jugadas de ajedrez — hace trabajo regex por cada chunk del sistema (presupuesto). Usa `asyncio.get_event_loop().create_task` que en 3.12+ puede ser `get_running_loop()`. La captura de `tool_call` también crea tasks sin await.
- **Fix:** Filtrar por `envelope.source` o `target` game; usar `asyncio.get_running_loop().create_task` dentro de `try`.
- **Esfuerzo:** S

### P2 — Mejora visual puppet (estética / polish) — no bloquea pero impacta percepción

#### P2-1 Sincronía courtroom: `talking` bob + `thinking` bubble pelean con `setRms`
- **Archivos:** `courtroom.html:64-72,542-598`, `kateto-avatar.js:263-279`
- **Qué pasa:** `zone.talking` activa `animation: talkbob 0.34s infinite`, mientras `setRms()` setea `transform: translate/rotate` por frame vía `style.transform` (inline) + `transition 0.04s`. La animación CSS gana sobre inline transform en algunos browsers (conflicto `animation` vs `transform`).
- **Fix:** Separar capas: wrapper `.bob` para talkbob y `.jaw` para RMS, o desactivar `animation` cuando `rawRms>0.015` y dejar solo transform RMS. Probar `will-change: transform` + `transform: translate3d`.
- **Esfuerzo:** M

#### P2-2 Curva puppet demasiado agresiva en `kateto-avatar.js`
- **Archivos:** `kateto-avatar.js:18-32`
- **Qué pasa:** `52px` vertical + `28px` lateral + `34deg` tilt es excesivo para los portraits actuales (probados con 190 px judge / 400 px sides) — corta cabeza o sale del `char-wrap`. Backend mapea a 16 px/4.5°; frontend duplica x3.
- **Fix:** Bajar a `18-22 px` vertical, `8-10 px` lateral, `6-8°` tilt; hacer parámetros configurables por voz (`avatar_scale`). Pasar `jawOffsetX` al backend en lugar de `Math.random()`.
- **Esfuerzo:** S

#### P2-3 Stage layout courtroom no responsive en ultrawide / mobile
- **Archivos:** `courtroom.html:85-163`
- **Qué pasa:** `left:2vw/right:2vw` + `width:26vw` + `height:62vh` deja gutters enormes en 21:9 y se solapa en 768 px. `#zone-center` con `transform: translateX(-50%)` colisiona con `left/right` en 3 debaters. `kateto-paper-transcript` a `right:1.2vw/bottom:11vh/21vw` tapa `zone-right` en 1280 px.
- **Fix:** Media queries: en `<1100px` apilar zones con `flex` o reducir `width` a `22vw`; en `<800px` pasar transcript a drawer inferior. Probar en OBS 1920×1080 (caso principal).
- **Esfuerzo:** M

#### P2-4 Typewriter pacing vs RMS desacoplados
- **Archivos:** `kateto-transcript.js:200-380`, `courtroom.html:510-516`, `kateto-avatar.js:300-420`
- **Qué pasa:** Courtroom aclara "courtroom is display-only, no TTS, only typewriter clicks" pero sigue escuchando `audio_output` para visemes. Transcript typewriter corre a `~28ms/char` (estimado) mientras `SubtitleStreamer` en `kateto-avatar.js` corre a `190 WPM / 315ms/word`. No hay sync word→jaw; la boca se mueve por RMS pero el texto se teclea a otra cadencia.
- **Fix:** Si courtroom es display-only, desactivar visemes por RMS y usar `pulseWord()` por cada word del typewriter (ya hace `paperTranscript.addTurn`); o mantener RMS pero sincronizar `onWord` del transcript con `avatar.pulseWord()`.
- **Esfuerzo:** M

#### P2-5 Falta `overlay_layout` positions para courtroom (game Bridge)
- **Archivos:** `kateto/plugins/visual_overlay/web/index.html` (no courtroom), `kateto/plugins/game_bridge/*`
- **Qué pasa:** Índice tiene `pos_jane=left` parsing; courtroom no. Game moves (chess) no disparan animación de "mueve pieza" en tribunal.
- **Fix:** Portar `customPositions` parsing + `handleOverlayLayout()` a courtroom; añadir transiciones suaves `top/left` 0.6s cubic ya usadas en index.html (línea `transition: top 0.6s ...`).
- **Esfuerzo:** S

#### P2-6 Pequeños pulidos sumados
- `courtroom.html:21` `#scene::after` vignette muy oscura tapa puppets en `filter: brightness(0.72)` inactive — aclarar a 0.82 o añadir luz de recorte.
- `kateto-paper-transcript` `SoundController` carga 14 wavs en paralelo al crear el elemento; en courtroom cada `popObjection` + typewriter compiten por `AudioContext` suspendido — mover `resume()` a primer click del usuario y lazy-load wavs.
- `assets/bate_debate/CREDITS.md` OK (CC0), pero faltan licencias de `clicking*.wav`/`return.mp3` (typing sounds) — añadir.
- `config/defaults/config.toml` no documenta `plugin.visual_overlay.layout/voices/audio` params registrados en `visual_overlay_plugin.py:192-196` — añadir ejemplo comentado.
- Duplicar `kateto-avatar.js` entre `web/kateto-avatar.js` y endpoint `/components/{file}` hace cache bust difícil — añadir `?v=` o `ETag` en `http_server:component_asset`.

---

## 3. Matriz de archivos exactos por hallazgo

| ID | Archivo(s) | Líneas |
|---|---|---|
| P0-1 | `kateto/core/rms.py` · `kateto/plugins/visual_overlay/visual_overlay_plugin.py` · `kateto/plugins/visual_overlay/web/kateto-avatar.js` · `kateto/plugins/visual_overlay/web/courtroom.html` · `kateto/plugins/visual_overlay/web/index.html` | `rms.py:49-70` · `visual_overlay_plugin.py:127,155,296` · `avatar.js:14-34,240-251` · `courtroom:589-598` |
| P0-2 | `assets/bate_debate/whisperer.png` (ausente) · `kateto/plugins/system/http_server.py` · `visual_overlay/web/kateto-avatar.js` · `voices/whisperer/` | `http_server:24` · `avatar.js:237-239` |
| P0-3 | `kateto/plugins/bate_debate/orchestrator.py` | `L185-232,356-379,470-523` |
| P0-4 | `kateto/plugins/visual_overlay/visual_overlay_plugin.py` · `visual_overlay/web/courtroom.html` · `visual_overlay/web/index.html` | `plugin:100-113` · `courtroom:544-605` · `index:565` |
| P1-1 | `kateto/core/rms.py` · `visual_overlay_plugin.py` · `courtroom.html` | `rms:73-122` · `plugin:50-62,148-189` |
| P1-2 | `orchestrator.py` | `386-411` |
| P1-3 | `orchestrator.py` · `kateto/plugins/audio_output/player.py` | `643-648` |
| P1-4 | `visual_overlay/web/courtroom.html` | `354-442` |
| P1-5 | `courtroom.html` | `457,475` |
| P1-6 | `orchestrator.py` | `568-578,830-921` |
| P1-7 | `visual_overlay_plugin.py` · `plugins/system/http_server.py` · `cli/commands.py` | `plugin:32` · `http_server:242-248,328-373` · `commands:343-354` |
| P1-8 | `plugins/system/http_server.py` | `24-26,205` |
| P1-9 | `plugins/system/http_server.py` | `383-413` |
| P2-1 | `courtroom.html` · `kateto-avatar.js` | `courtroom:64-72` · `avatar.js:263-279` |
| P2-2 | `kateto-avatar.js` | `18-32` |
| P2-3 | `courtroom.html` | `85-163` |
| P2-4 | `kateto-transcript.js` · `courtroom.html` | `transcript:200-380` · `courtroom:510-516` |
| P2-5 | `visual_overlay/web/index.html` vs `courtroom.html` | `index: customPositions` |
| P2-6 | `courtroom.html` · `kateto-transcript.js` · `config/defaults/config.toml` | varios |

---

## 4. Checklist de verificación sugerido (sin implementar)

Antes de cerrar cada P0/P1:

- [ ] `uv run pytest kateto/tests/test_bate_debate.py kateto/tests/test_visual_overlay.py -v` pasa (mock flow + avatar assets + overlay_layout + audio b64 + RMS).
- [ ] `uv run kateto debate --self-test --overlay` con `kateto run` levantado deja `paperTranscript` tecleando y mandíbulas moviéndose sin saltos; `whisperer` visible.
- [ ] `curl /api/courtroom/state` retorna `current` sin necesidad de WS conectado.
- [ ] `GET /voices/whisperer/avatar_head.png` 200 (o fallback controlado) y `assets/bate_debate/whisperer.png` 200.
- [ ] `courtroom.html` responde a `OverlayLayout(layout=sides, positions={jane:left, doktor:right})` moviendo zones.
- [ ] RMS: `map_rms_to_jaw_transform(0.525)==(8.0,2.25)` coincide con `computeJawKinematics` a factor 0.5 (o se usa payload).
- [ ] `interrupt` cierra boca inmediatamente (`setRms(0)` + `reset()` + `zone.talking` off).

---

## 5. Notas de auditoría

- No se modificó código (solo audit). No se tocó `AGENTS.md`.
- TODOs explícitos no hay (`TODO`/`FIXME` = 0 en ambos plugins) — la deuda es implícita (desalineaciones y faltantes).
- Tests actuales cubren bien el contrato (phrase-based pipeline assert, thinking ticks no en registry, `BrowserPcmPlayer` no en courtroom, `phase===thinking` presente) — fallarían si se unifican fórmulas sin actualizar expects en `test_visual_overlay.py:63-79`.
- Sonidos `bate_debate/sounds/clicking*.wav` (14) + `return.mp3` OK y servidos vía `/sounds/{file}`. Courtroom solo usa typewriter clicks (sin TTS), lo cual es intencional: no reproducir audio allí.

---

*Informe generado por subagente audit — dejar en* `AUDIT_bate_debate_visual_overlay_2026-09-02.md` *y referenciar desde PR/issue de puppet.*
