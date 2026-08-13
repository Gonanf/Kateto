Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/ops-ux (rama wt/ops-ux). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/ops-ux/docs/specs/2026-08-13-ops-ux.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §C1/C2/C3/H7 — fundamentación.

FEATURE: Ops UX — kateto setup, kateto doctor, kateto run --trace.
- kateto setup: wizard interactivo (CLI) que lee defaults versionados, pregunta por modelo LLM/TTS/ASR y endpoints, y escribe/actualiza la config de usuario con deep-merge (NO pisa config existente; keys a un archivo de secrets que la config referencia). NO reescribir config que el usuario ya tenga.
- kateto doctor: chequea en un reporte: (a) config válida (tomllib contra schema), (b) modelos en :11434 (existen, cargados, tool-calling si aplica), (c) servers whisper/TTS accesibles, (d) VAD presente, (e) keys presentes SIN imprimirlas (display enmascarado tipo sk-ef2...6599). Exit code no-cero si algo falla. Mensajes accionables.
- kateto run --trace: log de cada evento del bus con timestamp + delta desde el evento anterior + dispatch source→targets. Filtros --trace-events y --trace-voice. El log default NO cambia.
- La lectura de config SIEMPRE con tomllib (la api_key puede estar varias líneas abajo de su cabecera [plugin.x] — un grep de 1 línea da vacío y miente).
- Fuera de scope: FTS5/session search (YAGNI, un grep sobre logs alcanza), migración a YAML (se mantiene TOML), TUI nueva.

ARCHIVOS CLAVE: kateto/cli/commands.py (registro de comandos CLI), kateto/cli/registry.py, kateto/core/config.py (load_config, ConfigPaths, defaults), kateto/core/manager.py (PluginManager — dónde emite eventos, para el trace), kateto/run_mode.py (cómo arranca el runtime, para --trace), kateto/providers/ (health check de endpoints). Mirá kateto/cli/commands.py para seguir el patrón de comandos existente (Install, etc.).

CONVENCIONES:
- Config: TOML, user config en ~/.config/kateto es autoritativa — el setup la completa, NUNCA la pisa. Leer con tomllib.
- Ponytail: solución MÁS SIMPLE que funcione. El doctor no necesita async: chequeos secuenciales con timeout corto (httpx). Simplificaciones con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Prior art: kateto/tests/test_cli_connector.py (si existe), test_config.py. El doctor debe aceptar un "estado del entorno" inyectable para testearlo sin servers reales.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba cada comando de forma REAL (comandos exactos para correr kateto setup/doctor/trace).
