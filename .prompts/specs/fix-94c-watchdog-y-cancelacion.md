# Segunda pasada: los dos síntomas siguen (habla encima + una generación por fragmento)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`
(HEAD `466abc0`, ya commiteado). Seguí en esa rama. NO commitees: dejá el diff visible.
El usuario reporta que **los dos síntomas originales siguen**: (1) Kateto habla encima suyo, (2) una
generación por fragmento de Whisper. Arreglá las cuatro cosas de abajo; todas tienen causa verificable en
código. Nada de features fuera de esto.

## A. `_playback_active` no puede depender sólo del sentinel `final`
Hoy `on_audio_output` prende/apaga la ventana de playback con `not data.final`, pero ese `final=True` no es
confiable (bug 97 del repo: el player pierde oraciones en cola tras el final). Si se pierde, `_playback_active`
queda **True para siempre** y entonces: todo segmento se clasifica como bleed y se descarta (el usuario no se
transcribe nunca) y el barge-in compara contra un `_playback_rms` obsoleto → Kateto sigue hablando y él no
existe. Es exactamente el síntoma "habla sin importarle si yo estoy hablando".
- Fix: watchdog con `playback_idle_timeout` (knob nuevo, default **1.5 s**). Guardá `_last_playback_chunk_at`;
  si no llega ningún `audio_output` en ese lapso, considerá el playback terminado (`_playback_active=False`,
  `_playback_rms=0.0`). Verificalo sin threads (drain loop o el task del turno).
- Test: playback sin `final=True` + silencio posterior → pasada la ventana el listener vuelve a escuchar:
  el segmento siguiente NO se descarta y el barge-in compara contra 0.

## B. El descarte de bleed no debe depender de `interrupt_on_vad`
`_handle_closed_segment` sólo descarta el segmento si `self._config.interrupt_on_vad` es True. Ese flag
gobierna si se **interrumpe**, no si el audio es del usuario o del parlante: con `interrupt_on_vad=false`
(el workaround documentado) los segmentos del bleed entran al turno y Kateto se transcribe a sí misma.
Desacoplalo: el descarte depende sólo de `_playback_active` + que no haya barge-in concedido.

## C. Bug 106 — cancelación downstream del turno anterior (el "cancelarlo inmediatamente" del usuario)
Si arranca un turno nuevo mientras hay generación/TTS en vuelo, nada garantiza el corte. Implementá la señal
explícita **con el mínimo que resuelva**: al abrir un turno de usuario, el listener emite un `interrupt` con
`reason="user_turn"` (reusa `manager.interrupt`, que ya propaga `InterruptData` a quien corresponda) o, si
hace falta un contrato nuevo, un evento pydantic en `core/event.py` + `register_event` — pero **no dupliques
lógica que ya existe**:
- `VoiceAgent.on_interrupt` ya cancela `_generation_task` (voces).
- `edgetts.on_interrupt` ya corta el stream (TTS).
- Verificá que el purge de `token_queue`/`pcm_queue` de los pipelines (`voices/base.py`) y las lanes del
  player ocurran con ese interrupt; si alguno no reacciona, ese es el agujero a cerrar.
- No cambies la firma ni el contrato de los eventos existentes.
- Test: turno nuevo con generación en vuelo → task de generación cancelada y colas purgadas.

## D. Test end-to-end de la cadena (fakes, sin audio real ni servers)
Cableá listener → whisper (fake) → classifier (fake) → `generate` (fake) y verificá:
- 3 segmentos separados por menos que `turn_silence_timeout` → **1** llamada a `transcribe` y **1** `generate`.
- 2 turnos separados por más que `turn_silence_timeout` → 2 `transcribe` y 2 `generate`.
- Playback con bleed → **0** `transcribe`.
Este test es el que demuestra el síntoma del usuario: es obligatorio. Si no se puede por limitaciones de los
fakes, decilo explícitamente y explicá qué falta, en lugar de bajarlo o saltearlo.

## Verificación obligatoria (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/test_audio_barge_in.py kateto/tests/test_audio_input.py -q`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline actual: 446 passed / 4 failed preexistentes
   (`test_audio_capture::…raw_int16…`, `test_prompt_context::…session_headers`, 2 de `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Tocar la config del usuario, `capture.py`, `silero.py`, o la firma/contrato de eventos existentes.
- Usar la herramienta de subagentes/task: trabajá directo vos.
- Commitear o inventar verificación que no corriste.
