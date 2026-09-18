# Próximo bug (verificado): el flush de turno dispara mientras el usuario habla

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`
(HEAD `910da60`, ya mergeado a master). Seguí en esa rama. **NO commitees**: dejá el diff visible.

## Causa (verificada leyendo el código, no hipótesis)
`_rearm_turn_flush()` se llama **sólo** desde `_handle_closed_segment()` (al cerrar un segmento). Cuando el
usuario **retoma el habla** dentro de la ventana de `turn_silence_timeout`, el drain loop **no cancela** el
task pendiente: el `voice_started` sólo loguea, prende el indicador de grabación y llama a
`_interrupt_playback(mic_rms)`. El timer dispara igual →

`_flush_turn()` → `_emit_segment(parcial)` → whisper → transcription → classifier → generate

o sea: la voz contesta un **mensaje incompleto mientras el usuario sigue hablando**. Es exactamente lo que
el usuario reporta: "hablan pisándome y responden a mensajes incompletos". La acumulación de turno funciona
cuando el usuario calla, pero se rompe en cuanto reanuda antes de que venza el timer.

## Fix
1. Mientras haya habla del usuario, el flush **no puede dispararse**: al detectar habla en el drain loop,
   cancelá el task pendiente y no lo re-armes hasta que cierre el próximo segmento
   (`_handle_closed_segment` ya lo re-arma). No rompas:
   - el cap duro `max_turn_secs` (sigue forzando flush),
   - la cancelación en `deactivate`/disable,
   - `_turn_flush_later()` verifica `self._turn_flush_task is current_task()` (mantené esa guarda).
2. Diagnóstico (necesito poder distinguir fragmentación de ASR de corte por pausa genuina):
   - al emitir, loguear cuántos segmentos y cuántos ms acumuló y el motivo del cierre:
     `[mic] turn flush reason=silence segments=3 buffered_ms=4200`;
   - al cancelar por habla nueva: `[mic] turn flush cancelled: user resumed speaking`.
3. Knob `turn_hold_ms` (default **0** = comportamiento actual): vencido `turn_silence_timeout`, espera ese
   extra antes de emitir; si en ese extra vuelve el habla, cancela y sigue acumulando. Es el "acumulándose
   mientras hablo" con default neutro (no cambio latencia sin que lo decidan).

## Tests (obligatorios)
- Habla reanudada dentro de la ventana del turno → **0** `audio_chunk` emitidos y el buffer se fusiona
  (un único emit al final, con los dos segmentos concatenados).
- Silencio real (sin reanudar) → 1 emit.
- `max_turn_secs` alcanzado → sigue forzando el emit (no lo bloquea la cancelación por habla).
- `turn_hold_ms > 0` → retiene ese extra; si vuelve el habla dentro del hold, cancela y acumula.
- Regresión: los 36 tests actuales de la rama siguen verdes (no los debilites).

## Docs
- Bug nuevo con el **siguiente id libre** (verificá el máximo en `docs/src/content/docs/bugs/`): "el flush de
  turno dispara mientras el usuario habla", severidad Alta, componente `kateto/plugins/audio_input/listener.py`.
- `FIX-94.md`: sección nueva con esta causa, el fix, `turn_hold_ms` y el log de diagnóstico.
- `known-issues.md`: el bug nuevo en Abiertos (o Resueltos si queda cerrado y verificado).

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/test_audio_barge_in.py kateto/tests/test_audio_input.py kateto/tests/test_audio_turn_chain.py -q`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: 455 passed / 4 failed preexistentes
3. `git diff --stat`

## Prohibido
- Tocar la config del usuario, `capture.py`, `silero.py`, contratos de eventos existentes.
- Subagentes/task. Commitear. Inventar verificación.
