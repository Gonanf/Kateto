# FIX-94 — Falso barge-in: el micrófono escucha el propio parlante

Bug: `docs/src/content/docs/bugs/94-auto-barge-in-por-vad-escucha-propio-parlante.md` (Alta, aún `open` en el doc — actualizar a `resolved` al cerrar).

## Causa raíz (verificada en el código)

- `kateto/plugins/audio_input/listener.py:183` (antes del fix): `_interrupt_playback` solo chequeaba `interrupt_on_vad`; el flag `_playback_active`, seteado en `on_audio_output`/`set_playback_active` (`listener.py:131-135`), **nunca se consultaba** antes de interrumpir.
- Con parlantes (sin AEC ni headset), el propio TTS llega al mic, el Silero VAD dispara `voice_started` y `manager.interrupt(reason="voice_activity")` mataba generación/TTS/player lanes a la primera palabra. El `returncode 255` de ffmpeg era síntoma, no causa.

## Estrategia elegida: ventana de gracia (debounce) sobre el playback propio

Elegí **grace window por tiempo desde el inicio del playback propio** (en vez de exigir sostenimiento medido desde el onset del VAD): es un único punto de decisión (`_interrupt_playback`), no requiere cronómetros adicionales por segmento, y modela directamente el fenómeno físico — el bleed del parlante al mic es más intenso inmediatamente después de que arranca el TTS. Mientras el playback está activo:

- Actividad VAD **dentro** de la gracia → se ignora y se marca `_deferred_barge_in`; se re-chequea en cada frame de voz siguiente (`listener.py`, `_drain_callback_queue`), así el barge-in real **no se pierde**: si el habla persiste más allá de la gracia, `_interrupt_playback` dispara igual y loguea `vad interrupt: speech sustained …ms past barge-in grace`.
- Sin playback propio → se interrumpe exactamente como antes.
- `interrupt_on_vad = false` → early-return sin tocar nada del gating (workaround actual intacto).
- Al terminar la salida (`set_playback_active(False)`, `disable()`, y al disparar el interrupt) se limpia `_playback_started_at`/`_deferred_barge_in`, así la gracia nunca deja al sistema sordo.
- La gracia solo afecta al **interrupt**: la captura, el segmentado y el envío a ASR (`audio_chunk`) siguen funcionando igual (verificado por test).

## Knobs nuevos

| Knob | Default | Dónde |
|---|---|---|
| `barge_in_grace_ms` | `800.0` (`DEFAULT_BARGE_IN_GRACE_MS`, `base.py:23`) | `AudioInputConfig` (`base.py:66-69`), leído de `PluginSettings` vía `getattr` (config con `extra="allow"`, o sea configurable desde TOML por plugin). `0` desactiva la gracia. |

No se tocó `vad_threshold` ni `silence_timeout`: el problema es gating, no sensibilidad. (Nota: si en campo 800 ms sigue cortando, subir el knob antes que tocar el VAD.)

## Logs de diagnóstico

- `[mic] vad ignored: own playback within grace (…ms < …ms), barge-in deferred` — por qué NO se interrumpió.
- `[mic] vad interrupt: speech sustained …ms past barge-in grace, treating as real barge-in` — por qué SÍ.

## Cambios

- `kateto/plugins/audio_input/base.py`: `DEFAULT_BARGE_IN_GRACE_MS`, campo `barge_in_grace_ms` en `AudioInputConfig`, lectura en `from_settings`.
- `kateto/plugins/audio_input/listener.py`: tracking de `_playback_started_at`/`_deferred_barge_in`, gating en `_interrupt_playback`, re-check en el drain loop, resets en `enable`/`disable`/`set_playback_active`.
- `kateto/tests/test_audio_input.py`: `test_vad_interrupts_active_playback_once_per_playback_window` adaptado — ese test codificaba el comportamiento buggy (interrumpir de inmediato con playback recién iniciado). Se preservó su intención ("una sola interrupción por ventana de playback") adelantando `_playback_started_at` más allá de la gracia para modelar un barge-in real. No se debilitó ni borró ningún test.

## Cobertura de tests (`kateto/tests/test_audio_barge_in.py`, 8 tests)

| Test | Cubre |
|---|---|
| `test_vad_during_grace_of_own_playback_does_not_interrupt` | Playback propio + VAD en gracia → NO interrumpe + loguea el motivo |
| `test_sustained_speech_beyond_grace_interrupts_playback` | Habla sostenida más allá de la gracia → SÍ interrumpe (barge-in real) |
| `test_vad_without_own_playback_interrupts_immediately` | Sin playback propio → interrumpe como hoy |
| `test_interrupt_on_vad_false_never_interrupts[True/False]` | Flag apagado → nunca interrumpe, con y sin playback |
| `test_clearing_playback_flag_reopens_barge_in_after_grace` | El flag se limpia al terminar la salida → VAD vuelve a interrumpir |
| `test_grace_gates_only_the_interrupt_not_capture_or_asr` | El `audio_chunk`/ASR sigue fluyendo durante la gracia |
| `test_default_barge_in_grace_is_documented_and_configurable` | Default 800 ms y override por config |

Todos con manager y audio_output mockeados (captura fixture, Silero determinista, `set_playback_active` directo); sin micrófono real ni servers.

## Verificación (comandos y conteos exactos)

```
$ .venv/bin/python -m pytest kateto/tests/test_audio_barge_in.py -q
8 passed in 0.99s

$ .venv/bin/python -m pytest kateto/tests/ -q -k "audio or listener or vad or interrupt"
1 failed, 54 passed, 387 deselected
```

El único fallo, `test_audio_capture.py::test_sounddevice_capture_uses_raw_int16_mono_native_rate_input`, es **preexistente** y ajeno a este fix: el fake de `sounddevice.RawInputStream` del test no acepta el kwarg `latency` que `kateto/plugins/audio_input/capture.py:103` le pasa (no toqué `capture.py`). Este archivo está fuera del alcance de la regla 0.

## Qué NO se puede verificar sin audio real

- El valor del default (800 ms) contra bleed real de parlante: necesita medición con mic+parlantes reales (frecuencia de falso corte vs latencia percibida del barge-in). Si 800 ms es corto en hardware concreto, subir `barge_in_grace_ms` por config.
- Que el Silero VAD puntúe por encima del umbral el bleed real del parlante (asume que sí — el reporte del bug lo confirma empíricamente).
- Comportamiento con AEC/headset (allí la gracia es innecesaria pero inofensiva).

---

# FIX-94b — Barge-in real (stamping + discriminador por nivel) y acumulación de turno

## 1. Bug del stamping (causa raíz del "habla sin importarle si yo estoy hablando")

`set_playback_active(True)` re-stampeaba `_playback_started_at` en **cada** chunk
del TTS (un utterance = N eventos `AudioOutput(final=False)`, `final=True` recién
al final). `elapsed_ms` quedaba siempre < `barge_in_grace_ms` → barge-in diferido
para siempre → imposible cortar a Kateto durante todo el playback.

Fix (`listener.py`, `set_playback_active`): el stamp se setea **una sola vez por
ventana de playback** (transición inactivo→activo); los `True` repetidos hacen
early-return. `on_audio_output` además acumula el nivel de playback (`_playback_rms`,
EMA sobre `calculate_raw_rms` de `kateto/core/rms.py`).

## 2. Discriminador por nivel + habla sostenida

Sin AEC, tiempo solo no distingue bleed de barge-in. Decisión nueva en
`_interrupt_playback(mic_rms)` (el RMS del mic se calcula con la **misma función**
sobre el frame de 16 kHz int16 mono):

1. `interrupt_on_vad = false` → early return (workaround intacto).
2. Sin playback activo → interrumpe como siempre, sin condiciones.
3. Con playback: `elapsed < barge_in_grace_ms` → deniega (`grace`, mismo log de antes).
4. `mic_rms < playback_rms * barge_in_level_factor` → deniega (`reason=bleed`).
5. Habla sostenida por encima del nivel < `barge_in_min_speech_ms` → deniega
   (`reason=too-short`). El onset se resetea con cada silencio o denegación por
   gracia/bleed: solo cuenta habla que no se pudo atribuir al parlante.
6. Si pasa todo → corta ya + log `barge-in granted` con los números.

Logs con números para tunear por hardware:

- `[mic] barge-in granted mic_rms=… playback_rms=… factor=… sustained_ms=… elapsed_ms=…`
- `[mic] barge-in denied … reason=bleed|too-short …` (y el de `grace` preexistente).

## 3. Acumulación de turno (un `audio_chunk` por turno → cierra el bug 58 del lado listener)

- `_handle_closed_segment`: si hay playback activo sin barge-in, el segmento es
  bleed propio → **se descarta** (`[mic] segment attributed to own playback, dropped`),
  nunca entra al buffer (evita el loop de auto-transcripción).
- Si no, se anexa al `_turn_buffer`. Fin de turno = task asyncio que duerme
  `turn_silence_timeout` (default **2.0 s**), re-armada con cada segmento nuevo
  (sin sleeps bloqueantes ni threads). `silence_timeout` (1.0 s) sigue siendo el
  corte intra-turno: no se tocó.
- Cap duro `max_turn_secs` (default **30 s**): al alcanzarlo se emite lo acumulado.
- Un turno = un `_emit_segment`: `_last_resume_gap_ms`, `resumed_listening` y
  `duration_ms` funcionan igual.

## 4. Knobs nuevos (todos por `getattr`, compatibles con configs viejas)

| Knob | Default | Efecto |
|---|---|---|
| `barge_in_level_factor` | `1.3` | El mic debe superar `playback_rms × factor` |
| `barge_in_min_speech_ms` | `300.0` | Habla sostenida mínima para cortar |
| `turn_silence_timeout` | `2.0` | Silencio continuo que cierra el turno |
| `max_turn_secs` | `30.0` | Techo del buffer de turno |

Defaults comentados agregados en `config/defaults/config.toml`
(`[plugin.audio_input_mic]`). No se tocó `~/.config/kateto/`.

## 5. Tests adaptados (comportamiento viejo → nuevo, sin debilitar)

- `test_audio_barge_in.py::test_grace_gates_only_the_interrupt_not_capture_or_asr`
  → reemplazado por `test_playback_bleed_segment_is_attributed_and_dropped`:
  antes el bleed fluía a ASR durante la gracia; ahora se descarta (esa era la
  causa del loop de auto-transcripción).
- `test_audio_input.py::test_vad_interrupts_active_playback_once_per_playback_window`:
  además de adelantar el stamp, pre-data `_speech_onset_at` (el gate sostenido
  exige 300 ms de habla real; el fixture emite 2 frames en ~ms).
- Helpers `make_settings` de ambos archivos aceptan los knobs nuevos con
  `turn_silence_timeout` corto (el default 2.0 s excedería los `timeout=1` de espera).

Tests nuevos: stamp único ante N chunks (`test_repeated_playback_chunks…`),
grant fuerte+sostenido, deny por bleed, deny por habla corta, merge de 2 segmentos
en 1 chunk, flush único tras silencio, cap por `max_turn_secs`, defaults/overrides.

## 6. Qué NO se puede verificar sin audio real

- Calibración de `barge_in_level_factor` con su micrófono/parlantes: el 1.3 es un
  punto de partida; si el bleed corta (falso positivo) subirlo, si cuesta cortar
  (falso negativo) bajarlo. Los logs `granted/denied` traen los RMS medidos.
- Que el PCM de `AudioOutput.samples` (EdgeTTS, rate variable) sea comparable en
  amplitud con el frame del mic: ambos usan `calculate_raw_rms` (independiente del
  sample rate), pero la ganancia relativa parlante/mic es física y varía por equipo.
- Latencia percibida del corte con `barge_in_min_speech_ms=300` + gracia 800 ms.

---

# Segunda pasada (2026-09-18) — A/B/C/D: watchdog, desacople, user_turn, cadena e2e

Los dos síntomas originales seguían: (1) Kateto habla encima del usuario,
(2) una generación por fragmento de Whisper. Cuatro fixes, todos con causa
verificable en código.

## A. `_playback_active` no dependía solo del sentinel `final` (quedaba sordo para siempre)

`on_audio_output` prendía/apagaba la ventana con `not data.final`, pero ese
`final=True` no es confiable (bug 97: el player pierde oraciones en cola tras
el final). Si se perdía, `_playback_active` quedaba True para siempre: todo
segmento se descartaba como bleed (el usuario nunca se transcribía) y el
barge-in comparaba contra un `_playback_rms` obsoleto.

Fix (`listener.py`): watchdog con knob nuevo `playback_idle_timeout` (default
**1.5 s**). Se guarda `_last_playback_chunk_at` en cada `on_audio_output` con
samples; `_refresh_playback_idle()` (llamada desde el drain loop y desde
`_handle_closed_segment`, sin threads) cierra la ventana si no llega ningún
`audio_output` en ese lapso (`reopening mic`, `_playback_rms=0.0`).
`0` deshabilita el watchdog (early-return, si no el `>= 0` expiraría en el
primer frame).

## B. El descarte de bleed dependía de `interrupt_on_vad` (el workaround auto-transcribía)

`_handle_closed_segment` solo descartaba si `interrupt_on_vad` era True. Ese
flag gobierna si se **interrumpe**, no si el audio es del usuario o del
parlante: con `interrupt_on_vad=false` el bleed entraba al turno.

Fix: el descarte depende solo de `_playback_active` + ausencia de barge-in
concedido. Con el workaround el eco propio tampoco entra a Whisper.

## C. Bug 106 — cancelación downstream del turno anterior

Si arrancaba un turno nuevo con generación/TTS en vuelo, nada garantizaba el
corte. Al abrir un turno de usuario (primer segmento con buffer vacío y
`interrupt_on_vad=false`, donde antes no había señal alguna) el listener emite
`interrupt(reason="user_turn")` vía `manager.interrupt` — sin cambiar firmas
ni contratos, reusando handlers existentes: `VoiceAgent.on_interrupt` cancela
`_generation_task` y purga `token_queue`/`pcm_queue`; EdgeTTS corta el stream;
el player limpia las lanes. (Con `interrupt_on_vad=true` el `voice_activity`
ya cubre el corte, por eso la señal solo se emite en modo workaround.)

## D. Test end-to-end de la cadena (`kateto/tests/test_audio_turn_chain.py`)

Listener → whisper (fake) → classifier (fake) → `generate`: 3 segmentos
separados por menos que `turn_silence_timeout` → 1 `transcribe` + 1 `generate`;
2 turnos separados por más → 2 + 2; playback con bleed → 0 `transcribe`.

## Knobs nuevos de la pasada

| Knob | Default | Efecto |
|---|---|---|
| `playback_idle_timeout` | `1.5` (`0` lo deshabilita) | Sin `audio_output` en esa ventana → playback terminado |
| `barge_in_level_factor` | `1.3` | El mic debe superar `playback_rms × factor` |
| `barge_in_min_speech_ms` | `300.0` | Habla sostenida mínima para cortar |
| `turn_silence_timeout` | `2.0` | Silencio continuo que cierra el turno |
| `max_turn_secs` | `30.0` | Techo del buffer de turno |

## Qué queda sin verificar (requiere hardware real)

- Calibración de `barge_in_level_factor` con micrófono y parlantes reales: el
  1.3 es un punto de partida; si el bleed corta (falso positivo) subirlo, si
  cuesta cortar (falso negativo) bajarlo. Los logs `granted/denied` traen los
  RMS medidos para tunear por equipo.

---

# FIX-94e — El flush de turno disparaba mientras el usuario habla (bug 107)

Bug: `docs/src/content/docs/bugs/107-flush-de-turno-dispara-mientras-el-usuario-habla.md`
(Alta, `resolved` 2026-09-18).

## Causa (verificada en el código, no hipótesis)

`_rearm_turn_flush()` se llamaba sólo desde `_handle_closed_segment()` (al cerrar
un segmento). Cuando el usuario retomaba el habla dentro de la ventana de
`turn_silence_timeout`, el drain loop no cancelaba el task pendiente: el
`voice_started` sólo logueaba, prendía el indicador de grabación y llamaba a
`_interrupt_playback(mic_rms)`. El timer disparaba igual →
`_flush_turn()` → `_emit_segment(parcial)` → whisper → transcription →
classifier → generate. La voz contestaba un mensaje incompleto mientras el
usuario seguía hablando.

## Fix (`kateto/plugins/audio_input/listener.py`)

- En `_drain_callback_queue`, al detectar habla con `_playback_active` en falso
  (habla real, no bleed propio) y task pendiente: `self._cancel_turn_flush()` +
  log `[mic] turn flush cancelled: user resumed speaking`. No se re-arma hasta
  que cierra el próximo segmento (`_handle_closed_segment` ya lo re-arma).
- No se rompe: el cap duro `max_turn_secs` sigue forzando el flush en
  `_handle_closed_segment` (`reason=max_turn`); la cancelación en
  `disable()`/`enable()` intacta; la guarda
  `self._turn_flush_task is current_task()` en `_turn_flush_later()` se mantiene.
- La cancelación se gatea con `not self._playback_active` (evaluado después de
  `_interrupt_playback`, que limpia el flag en un barge-in concedido): el bleed
  del parlante no cancela el turno pendiente — si lo hiciera, el buffer quedaría
  varado porque los segmentos de bleed se descartan sin re-armar.

## Diagnóstico

- Al emitir (`_flush_turn`): `[mic] turn flush reason=silence|max_turn
  segments=N buffered_ms=M` — N = segmentos acumulados (`_turn_segments`), M =
  `int(duration_ms(buffer))`. Distingue fragmentación de ASR de corte por pausa
  genuina.
- Al cancelar por habla nueva: `[mic] turn flush cancelled: user resumed speaking`.

## Knob nuevo

| Knob | Default | Efecto |
|---|---|---|
| `turn_hold_ms` | `0.0` (`DEFAULT_TURN_HOLD_MS`, `base.py`) | Vencido `turn_silence_timeout`, espera ese extra (ms) antes de emitir; si vuelve el habla en ese extra, cancela y sigue acumulando. `0` = comportamiento actual, sin cambio de latencia. |

`AudioInputConfig.turn_hold_ms` leído de `PluginSettings` vía `getattr`
(compatible con configs viejas, igual que los knobs anteriores).

## Tests (`kateto/tests/test_audio_turn_flush.py`, 5 tests)

| Test | Cubre |
|---|---|
| `test_turn_hold_ms_default_is_zero_and_configurable` | Default 0 + override |
| `test_resumed_speech_cancels_pending_flush_and_merges` | Habla reanudada en ventana → 0 emits + merge en un único emit + logs cancelled/silence |
| `test_genuine_silence_flushes_single_chunk` | Silencio real → 1 emit + `reason=silence segments=1` |
| `test_max_turn_secs_still_forces_emit_despite_resumed_speech` | Cap duro fuerza el emit aunque el habla cancele el timer |
| `test_turn_hold_ms_retains_and_cancels_on_speech_within_hold` | Hold retiene el extra; habla dentro del hold cancela y acumula |

Regresión: los 36 tests de `test_audio_barge_in.py` + `test_audio_input.py` +
`test_audio_turn_chain.py` siguen verdes sin modificarlos.

## Qué NO se puede verificar sin audio real

- El valor de `turn_hold_ms` contra habla real con pausas (el 0 neutro no cambia
  latencia; subirlo solo si el usuario hace pausas largas intra-frase que hoy
  cortan el turno).
- Que el `reason=silence` corresponda a pausa genuina y no a VAD que sub-segmenta
  por ruido: el log trae `segments` + `buffered_ms` para decidirlo en campo.

---

# FIX-94f — TurnGate: los turnos encolados no se descartan tras un barge-in del usuario (bug 108)

Bug: `docs/src/content/docs/bugs/108-turnos-encolados-no-se-descartan-tras-barge-in.md`
(Alta, `resolved` 2026-09-18).

## Causa (verificada leyendo el código, no hipótesis)

`TurnGate.decide()` devuelve `Decision.QUEUE` cuando `self._active is not None`;
`VoiceAgent` entonces encola el turno en `TurnGate._pending` (`gate.enqueue(...)`
en `voices/base.py:_pass_turn_gate`) y `_drain()` lo re-emite cuando la voz queda
idle (`on_voice_idle` / `on_voice_status(IDLE)` / `on_audio_output_status` sin
PLAYING). `on_interrupt()` limpiaba `_active`/`_active_prompt` y ponía
`_steering = True`, pero **no tocaba `_pending`**. Secuencia del síntoma: el
usuario interrumpe → la voz se calla → los fragmentos siguientes del usuario
generan más `generate` → el primero ejecuta y los demás se encolan → cuando la
voz queda idle, `_drain()` los emite de a uno → "me habló después" con los
mensajes acumulados. El `_steering` bloquea el drenado inmediato, pero el próximo
`decide` externo lo limpia (`_steering = False`) y el idle siguiente drena la
cola vieja.

## Fix (`kateto/plugins/system/turn_gate.py`, sin cambios de firmas ni contratos)

- `on_interrupt`: si el interrupt viene del **usuario** (reason en
  `{"voice_activity", "user_turn"}`), descarta la cola (`_pending.clear()`) y
  loguea `turn_gate: dropped N queued turn(s) on user interrupt`. Los follow-ups
  entre voces (otro reason/dept) mantienen el comportamiento actual: la cola sobrevive.
- Diagnóstico de cola: al encolar, `turn_gate: queued <event>(<target>) pending=<n>`
  (el log de `draining` ya existía). El próximo log muestra si se acumula.

## Tests (`kateto/tests/test_turn_gate.py`, 3 nuevos)

| Test | Cubre |
|---|---|
| `test_user_interrupt_drops_queued_turns_and_nothing_drains` | Cola con 2 pendientes + interrupt de usuario → `_pending` vacío y ningún drenado posterior (recorder no recibe nada) |
| `test_non_user_interrupt_keeps_queue_and_drains_as_followup` | Interrupt no-usuario (`handoff`) → la cola sobrevive y drena como hoy (regresión del follow-up) |
| `test_new_user_generate_executes_after_user_interrupt_flush` | Tras el flush, un `generate` nuevo del usuario **ejecuta** (no bloqueado por `_steering`) |

Cambio intencional en 1 test existente: `test_two_generates_different_voices_queue_second_turn`
esperaba que el turno encolado de doktor drenara tras un interrupt de usuario — eso
**era** el bug (turno de usuario acumulado contestado después). Ahora espera 0
llamadas de doktor; el drenado de follow-ups queda cubierto por la regresión nueva.
Ningún otro test existente se tocó.

## Qué NO se puede verificar sin audio real

- Que la razón del interrupt en campo sea siempre `voice_activity`/`user_turn` para
  habla real del usuario: si algún path emite otro reason para habla de usuario, la
  cola sobreviviría. El log `dropped N ...` lo muestra en cada barge-in.
