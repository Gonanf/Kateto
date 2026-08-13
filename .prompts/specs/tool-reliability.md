Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/tool-reliability (rama wt/tool-reliability). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/tool-reliability/docs/specs/2026-08-13-tool-reliability.md — la spec. Implementala tal cual (Problem Statement, Implementation Decisions, Testing Decisions).
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §A6/G6/G4 — fundamentación de la investigación.

FEATURE: Confiabilidad de tools.
- Guardia de truncamiento: si el LLM corta con stop_reason == "length", NO ejecutar los tool calls de ese turno (argumentos posiblemente corruptos); devolver al modelo un error estructurado pidiendo reintentar.
- Preflight de tool args: sanitizar strings (escapes/caracteres de control) y validar contra el schema Pydantic antes de invocar; si falla, error estructurado al modelo, no ejecutar.
- Soporte terminate:true: si las tools de un lote marcan terminate, no llamar al LLM de nuevo.
- FauxProvider: implementación de test del provider de LLM (OpenAI-compatible/pydantic-ai) con guión de pasos (chunks temporizados, tool calls, errores, delays), determinista y offline, para testear el pipeline sin modelos reales.

ARCHIVOS CLAVE: kateto/voices/base.py (loop de voz pydantic-ai harness), kateto/voices/tools.py (VoiceToolExecutor, capacidades), kateto/core/workflow.py, kateto/providers/ (providers OpenAI-compatibles), kateto/tests/ (tests existentes, mirá test_voices/test_tools como prior art).

CONVENCIONES:
- Eventos: contratos Pydantic en kateto/core/event.py. NO cambiar contratos existentes.
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla. Leer con tomllib.
- Ponytail: implementá la solución MÁS SIMPLE que funcione. Stdlib primero, sin abstracciones innecesarias. Simplificaciones deliberadas marcadas con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Corré también los tests de voices/tools existentes para no romper nada.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL en el runtime (no tests).
