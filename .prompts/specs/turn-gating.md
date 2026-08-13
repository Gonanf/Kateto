Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/turn-gating (rama wt/turn-gating). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/turn-gating/docs/specs/2026-08-13-turn-gating.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §A8/H2/G5/H8 — fundamentación.

FEATURE: Gating de turno + Steering/Follow-up + Barge-in.
- VoiceTurnState por voz (idle/thinking/speaking) alimentado SOLO por eventos del bus existentes (speak, audio_output, voice_idle, interrupt, transcription). NO crear un singleton global nuevo: el estado se deriva del bus.
- Gate de turno: en el camino generate→voz, antes de llamar al LLM: si mixer ocupado / turno en vuelo / clasificador IGNORE / latch de barge-in → encolar como Follow-up o descartar según política. Mata respuestas duplicadas.
- Colas duales: Steering = VAD detecta habla del usuario durante generación → abortar stream de la voz activa (asyncio.Event) + mensaje del usuario con prioridad al siguiente turno. Follow-up = request_generation inter-voz se procesa cuando la voz activa terminó y el usuario no intervino.
- Barge-in real: VAD habla humana → interrupt del LLM stream (cancelar generación) + stop del TTS/playback + latch de barge-in en la voz.

ARCHIVOS CLAVE: kateto/core/manager.py (dispatch de eventos, _resolve_subscribers), kateto/core/event.py (contratos — NO cambiar los existentes; si hace falta un evento nuevo, crealo con EventModel), kateto/plugins/system/voice_manager.py (enruta speak), kateto/plugins/executor/classifier.py (emite generate), kateto/plugins/audio_input/listener.py (VAD, voice_started → interrupt), kateto/plugins/audio_output/player.py (mixer), kateto/plugins/executor/interrupt.py (Interrupt Executor existente — no duplicarlo, integrarse). Mirá docs/run-mode-SPEC.md si necesitás entender el wiring.

CONVENCIONES:
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla. Leer con tomllib.
- Ponytail: solución MÁS SIMPLE que funcione. Si el gate se puede resolver con una comparación y una cola, eso es. Simplificaciones con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Prior art: kateto/tests/test_event_bus.py, test_plugin_manager.py, tests del interrupt.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL en el runtime (no tests).
