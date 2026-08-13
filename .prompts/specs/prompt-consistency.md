Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/prompt-consistency (rama wt/prompt-consistency). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/prompt-consistency/docs/specs/2026-08-13-prompt-consistency.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §A1/A2/G2/H1 — fundamentación.

FEATURE: Prompt estable + SOUL caching por voz.
- ContextBuilder por voz: módulo único que arma el contexto LLM en secciones ordenadas [SOUL estable] → [Tool schemas] → [Memoria durable] → [Historial reciente] → [Contexto volátil]. Todo prompt de voz pasa por él.
- System prompt construido UNA vez al spawnear la voz; rebuild solo ante compresión de contexto o entre sesiones, nunca por turno.
- SOUL de solo lectura durante la sesión: las mutaciones (voice_soul_manager) escriben snapshot versionado que se aplica en el próximo spawn, no en caliente.
- Prompt caching: prompt_cache_key fijo por voz + headers de sesión en providers OpenAI-compatibles que lo soporten; requests de fondo (clasificador, resúmenes) sin escritura de cache o namespace distinto.
- max_tokens/retries/timeout configurables por voz en config (hoy hardcodeados).

ARCHIVOS CLAVE: kateto/voices/base.py (VoiceAgent, _stream_response), kateto/voices/factory.py (create_voice, VoiceProfile), kateto/voices/memory.py (VoiceMemory), kateto/plugins/voice_soul_manager/ (mutación en caliente → snapshot versionado, ZODB ya existe en core), kateto/core/config.py (settings), kateto/core/event.py. Mirá también el harness pydantic-ai (Agent(model, system_prompt, toolsets, capabilities)) para entender dónde entra el system prompt.

CONVENCIONES:
- Eventos: contratos Pydantic en kateto/core/event.py. NO cambiar contratos existentes.
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla, NO reescribirla. Leer con tomllib. El nuevo setting por voz va en config/defaults/config.toml como default y el código lo lee con fallback al default.
- Ponytail: solución MÁS SIMPLE que funcione. Stdlib primero. Simplificaciones deliberadas con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Prior art: kateto/tests/test_config.py, test_storage.py, test_event_bus.py.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL en el runtime (no tests).
