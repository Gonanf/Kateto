Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/memory-ledger (rama wt/memory-ledger). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/memory-ledger/docs/specs/2026-08-13-memory-ledger.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §D5/H3/G3 — fundamentación.

FEATURE: Memoria de 2 capas (VoiceMemoryLedger).
- SOUL readonly: voice_soul_manager deja de mutar SOUL.md/JOURNAL.md en caliente; las memorias van al ledger. El SOUL solo cambia entre sesiones vía snapshot versionado (SoulSnapshotStore ZODB ya existe — kateto/core/ o donde esté).
- VoiceMemoryLedger: almacén JSON/SQLite por voz con colecciones tipadas (facts, relationships, action_patterns). Escritura atómica con lock, validación Pydantic antes de escribir, replace/remove por substring corto único.
- Inyección: bloque <VOICE_MEMORY> compacto inyectado UNA vez al inicio de sesión, después del SOUL. Nada de re-inyección mid-session.
- Tool refine_memory(fact, category, evidence): la voz agrega/actualiza/borra memorias con snapshot antes/después y rollback si la validación falla.
- Scoping por departamento: fun = memoria de stream; work/management = memoria de proyectos (Doktor/Conquest).
- Capa episódica (ChromaDB/Q-A autogenerados): SOLO dejar el seam/tool listo si es trivial; la fase 2 completa queda fuera de scope. Ponytail: si no es trivial, NO lo implementes, dejalo anotado.

ARCHIVOS CLAVE: kateto/voices/memory.py (VoiceMemory, VoiceFileStore en core/storage.py), kateto/plugins/voice_soul_manager/ (mutación → reemplazar por ledger + snapshot), kateto/voices/tools.py (registro de tools para las voces — agregar refine_memory), kateto/voices/base.py (dónde se arma el prompt, para inyectar el bloque), kateto/core/storage.py (path isolation), config de voces en config/defaults.

CONVENCIONES:
- Eventos: contratos Pydantic en kateto/core/event.py. NO cambiar contratos existentes.
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla. Leer con tomllib.
- Ponytail: solución MÁS SIMPLE que funcione. JSONL/SQLite con stdlib primero; no agregues deps nuevas para esto. Simplificaciones con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Prior art: kateto/tests/test_storage.py, test_config.py.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL en el runtime (no tests).
