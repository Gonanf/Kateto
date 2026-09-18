# Pasada final (chica): guard del watchdog + docs

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
Ya están aplicados A/B/C/D de la pasada anterior (diff sin commitear). Faltan dos cosas chicas.

## 1. `playback_idle_timeout = 0` documentado como "deshabilita" pero hace lo contrario
`DEFAULT_PLAYBACK_IDLE_TIMEOUT` está comentado como "0 disables it", pero
`_refresh_playback_idle()` compara `(monotonic() - last) >= self._config.playback_idle_timeout`: con 0
siempre da verdadero, así que en el primer frame se apaga la ventana de playback (justo lo opuesto).
- Fix: early return si `self._config.playback_idle_timeout <= 0` (semántica documentada), con el comentario
  alineado.
- Test: con `playback_idle_timeout=0`, playback activo + silencio largo → `_playback_active` sigue en True,
  no se loguea `reopening mic`, y el segmento se sigue atribuyendo al playback (drop).
- No toques el default (1.5 s) ni el resto del watchdog.

## 2. Docs de esta pasada (el repo documenta todo bug que se toca)
- `docs/src/content/docs/bugs/106-una-generacion-por-fragmento-falta-gating-downstream.md` → `status: resolved`,
  campos de fecha, y "Solución aplicada" describiendo: acumulación de turno (un `audio_chunk` por turno) +
  señal `interrupt(reason="user_turn")` al abrir turno de usuario, reusando los handlers existentes
  (`VoiceAgent.on_interrupt` cancela `_generation_task` y purga colas; TTS corta stream; player limpia lanes).
- `docs/src/content/docs/bugs/94-…`: agregá en "Solución aplicada" el watchdog `playback_idle_timeout`
  (el `final=True` no es fiable, bug 97) y el desacople del descarte respecto de `interrupt_on_vad`.
- `docs/src/content/docs/bugs/known-issues.md`: mové 106 de Abiertos a Resueltos.
- `FIX-94.md`: sección "Segunda pasada" con A/B/C/D, knobs nuevos (`playback_idle_timeout`,
  `barge_in_level_factor`, `barge_in_min_speech_ms`, `turn_silence_timeout`, `max_turn_secs`) y qué queda
  sin verificar (calibración de `barge_in_level_factor` con micrófono y parlantes reales).
- Si existe una página del pipeline de audio en `docs/src/content/docs/runtime/`, sumale los knobs; si no
  existe, no la inventes.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/test_audio_barge_in.py kateto/tests/test_audio_input.py kateto/tests/test_audio_turn_chain.py -q`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: 454 passed / 4 failed preexistentes
3. `git diff --stat` (sin commitear)
