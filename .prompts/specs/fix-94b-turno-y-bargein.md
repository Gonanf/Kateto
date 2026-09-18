# Fix: barge-in real + acumulación de turno en el listener del micrófono

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein` (detached en `9bf88df`).
El working tree YA tiene un patch sin commitear documentado en `FIX-94.md`: una ventana de gracia de
800 ms para el falso barge-in por bleed del parlante. **No lo revirtás: corregilo y completalo.**
No commitees, no cambies de rama, no toques la config del usuario (`~/.config/kateto/`).

## Síntoma reportado (textual del usuario)
> "ahora está hablando sin importarle si yo estoy hablando, y además por cada cosa que transcribe el
> Whisper.cpp (que muchas veces parte el texto como si hubiera terminado) se genera una petición para
> generarlo, y debería estar acumulándose mientras hablo y no generarse nada o cancelarlo inmediatamente
> (interrupción)"

Objetivo: **mientras el usuario habla no se genera nada**, se acumula el turno y se genera UNA vez al
final; y si Kateto está hablando y el usuario arranca, se corta **ya**.

## Causa raíz #1 — el barge-in está muerto durante todo el playback (verificada leyendo el código)
`AudioInputPlugin.on_audio_output` (`kateto/plugins/audio_input/listener.py`) llama
`set_playback_active(not data.final)`. El TTS emite **muchos** `AudioOutput(final=False)` por utterance
(`kateto/plugins/audio_output/edgetts.py:231` y `:258`; `final=True` recién en `:282`).
El patch actual hace:

```python
def set_playback_active(self, active: bool) -> None:
    self._playback_active = active
    if active:
        self._playback_started_at = monotonic()   # <-- se re-stampea en CADA chunk
```

Resultado: `elapsed_ms` siempre < `barge_in_grace_ms` → `_deferred_barge_in = True` para siempre →
`_interrupt_playback` retorna sin interrumpir mientras habla. El barge-in del usuario queda imposible
durante todo el playback. **Ese es el bug de "habla sin importarle si yo estoy hablando".**

## Causa raíz #2 — una generación por fragmento de Whisper (no hay noción de TURNO)
`VadSegmenter.consume` cierra segmento cuando el silencio supera `silence_timeout` (1.0 s en la config
del usuario) y `_emit_segment` emite un `audio_chunk` por segmento. De ahí: `whisper → transcription →
classifier → generate → speak`, una vez por fragmento. Whisper además transcribe el fragmento como frase
terminada (parte mal el texto). Ya está documentado en
`docs/src/content/docs/bugs/58-whisper-transcribes-per-chunk.md` con el fix direccional correcto
(acumular PCM y transcribir una sola vez al fin de habla), sin aplicar.

## Trabajo

### 1. Barge-in real con discriminador por nivel
Stamping: `_playback_started_at` se setea **una sola vez por ventana de playback** (transición
inactivo→activo) y nunca se re-stampea mientras siga activo.

La decisión no puede ser sólo por tiempo: sin AEC el micrófono escucha el parlante, así que una gracia
temporal o deja pasar el bleed (falso corte, bug 94) o silencia el barge-in (bug de hoy). Discriminador
por **nivel**, que ya está a mano sin agregar dependencias:

- El listener ya recibe `audio_output` con el PCM de lo que suena (`AudioOutput.samples`). Calculá el
  nivel de playback con `kateto/core/rms.py` (`RMSProcessor` o `calculate_raw_rms`) sobre `data.samples`,
  guardalo en `self._playback_rms` (suavizá con EMA, `RMSProcessor` ya lo hace).
- Calculá el nivel del frame de micrófono con **la misma función** sobre el frame de 16 kHz int16 mono
  (comparación comparable; no mezcles escalas).
- **Interrumpir requiere las tres**: (a) `is_speech` verdadero, (b) `mic_rms >= playback_rms * barge_in_level_factor`
  (default 1.3), (c) habla sostenida >= `barge_in_min_speech_ms` (default 300 ms) medida desde el onset
  del habla que no se pudo atribuir al playback. Sin playback activo → se interrumpe como hoy, sin condiciones.
- Knobs nuevos en `AudioInputConfig` + `from_settings` leídos por `getattr` (PluginSettings es `extra="allow"`,
  compatible con configs viejas): `barge_in_level_factor`, `barge_in_min_speech_ms`. `barge_in_grace_ms`
  existente queda como gracia de **onset** (sólo los primeros N ms del playback, ahora con stamping correcto).
- `interrupt_on_vad = false` → early return sin tocar nada (workaround intacto).
- **Log en cada decisión con los números**, así el usuario puede tunear con su hardware:
  `[mic] barge-in granted mic_rms=0.12 playback_rms=0.05 factor=1.3 sustained_ms=420 elapsed_ms=900`
  y análogo para `denied` (con el motivo: `bleed`, `too-short`, `grace`).

### 2. Acumulación de turno: UNA transcripción por turno
- El listener acumula el PCM de segmentos consecutivos y emite **un solo** `audio_chunk` por turno:
  - Fin de turno = silencio continuo >= `turn_silence_timeout` (default **2.0 s**) contado desde el cierre
    del último segmento.
  - Cap duro `max_turn_secs` (default **30 s**): al alcanzarlo se emite lo acumulado y arranca turno nuevo.
  - Si el usuario reanuda el habla antes de `turn_silence_timeout`, los segmentos se fusionan en el MISMO
    turno: nunca se emite el fragmento anterior.
  - Se emite un único `audio_chunk` con el buffer completo (una sola pasada de Whisper → cierra el bug 58).
  - El flush por tiempo necesita un task asyncio con deadline, cancelado/re-armado cuando llega habla nueva.
    Nada de sleeps bloqueantes ni threads.
- **Atribución (evita el loop de auto-transcripción)**: mientras `_playback_active` es True y NO se cumple
  el criterio de barge-in, el segmento se atribuye al bleed del propio parlante y **se descarta** (nunca
  entra al buffer de turno; log `[mic] segment attributed to own playback, dropped`). El frame que sí
  dispara un barge-in real abre turno de usuario con normalidad.
- `silence_timeout` (1.0 s) sigue siendo el corte intra-turno: **no lo toques**, el fin de turno lo decide
  el knob nuevo. `_last_resume_gap_ms`, `resumed_listening` y `duration_ms` siguen funcionando igual
  (un turno = un `_emit_segment`).

### 3. Config
No edites la config del usuario. Documentá los knobs nuevos en `FIX-94.md` y, si corresponde, agregá los
defaults comentados en `config/defaults/config.toml` bajo `[plugin.audio_input_mic]`.

### 4. Tests (obligatorios, sin micrófono ni servers reales)
Extendé `kateto/tests/test_audio_barge_in.py` y `kateto/tests/test_audio_input.py` cubriendo:
- Playback multi-chunk (varios `final=False`) con `playback_rms` bajo + usuario hablando fuerte y sostenido → **interrumpe** (regresión del stamping).
- Mismo escenario con `mic_rms <= playback_rms * factor` → **no** interrumpe (bleed) y loguea el motivo.
- Habla corta (< `barge_in_min_speech_ms`) → no interrumpe.
- Sin playback activo → interrumpe igual que hoy.
- `interrupt_on_vad=false` → nunca interrumpe (con y sin playback).
- Dos segmentos separados por menos que `turn_silence_timeout` → **un** `audio_chunk` con el PCM concatenado.
- Silencio >= `turn_silence_timeout` → un `audio_chunk` (no dos).
- `max_turn_secs` alcanzado → emite lo acumulado.
- Bleed durante playback sin barge-in → **ningún** `audio_chunk` emitido.
No debilites ni borres asserts existentes: si un test codificaba el comportamiento viejo, adaptalo y
explicá en el doc por qué.

### 5. Documentación
- Actualizá `FIX-94.md`: sección nueva con el fix del stamping, el discriminador por nivel, los knobs y
  "qué no se puede verificar sin audio real" (calibración de `barge_in_level_factor` con su micrófono/parlantes).
- `docs/src/content/docs/bugs/94-auto-barge-in-por-vad-escucha-propio-parlante.md` → `status: resolved` + solución aplicada.
- Bug nuevo con el **siguiente id libre** (verificá el máximo en `docs/src/content/docs/bugs/`): "una
  generación por fragmento de Whisper — falta acumulación de turno", severidad Alta, componente
  `kateto/plugins/audio_input/listener.py`. Actualizá la tabla de `docs/src/content/docs/bugs/known-issues.md`
  (94 → Resueltos, el nuevo → Abiertos).

## Verificación (reportá los números exactos, no "todo ok")
1. `.venv/bin/python -m pytest kateto/tests/test_audio_barge_in.py kateto/tests/test_audio_input.py -q`
2. `.venv/bin/python -m pytest kateto/tests/ -q -k "audio or listener or vad or interrupt or whisper"`
3. `git diff --stat`

Baseline medido antes de este brief: `test_audio_barge_in.py` 8 passed; con `test_audio_input.py` 19 passed.
En el filtro amplio hay **1 fallo preexistente y ajeno**: `test_audio_capture.py::test_sounddevice_capture_uses_raw_int16_mono_native_rate_input`
(el fake de `sounddevice.RawInputStream` no acepta el kwarg `latency` que pasa `capture.py:103`).
No lo arregles (fuera de alcance) pero confirmá que sigue siendo el único.

## Prohibido
- Tocar `capture.py`, `silero.py` o la config del usuario; levantar servers (usá los fixtures/mocks existentes).
- Usar la herramienta de subagentes/task: trabajá directo vos y hacé el trabajo completo.
- Commitear: dejá el diff visible para revisión.
- Reportar verificación que no corriste.
