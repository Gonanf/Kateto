Sos un ingeniero implementando una feature en Kateto: un voice team event-driven en Python 3.12 (bus de eventos pub/sub PluginManager, voces-LLM con system prompt SOUL, pipeline mic→VAD→ASR→clasificador→voice_manager→LLM streaming→TTS→mixer). Trabajás en un worktree limpio: /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/streaming-latency (rama wt/streaming-latency). Dependencias ya instaladas (uv sync hecho).

LEÉ PRIMERO:
1. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto-wts/streaming-latency/docs/specs/2026-08-13-streaming-latency.md — la spec. Implementala tal cual.
2. /home/chaos/proyectos/harness-research/brainstorm-kateto.md §B1/B2/B3/G1/D1 — fundamentación. Y docs/bugs/58-60-*.md del repo.

FEATURE: Latencia de streaming (EventStream dual + TTS buffered + client reuse).
- VoiceEventStream: AsyncIterator de deltas de texto + final_message() (Future con mensaje completo, usage, stop reason). Alimenta el data plane existente (token_queue) sin romperlo.
- Segmentación por frase: el consumidor acumula hasta delimitador (., !, ?, \n) y despacha la frase completa al TTS. El TTS arranca con la primera frase lista, no al final del turno.
- Buffering TTS AGNÓSTICO DEL PROVIDER: hoy EdgeTTS o Boson TTS; Zonos2 vendrá después. La capa de audio_output recibe frases (no tokens) y las sintetiza con el provider configurado. Para providers streaming (Zonos) modo incremental por frase; para no-streaming, encolar la frase y reproducir al recibir audio.
- ProviderRegistry: un client HTTP por endpoint, creado una vez y reutilizado (hoy se recrea por llamada — bug 59). Config por modelo desde la config existente.
- NO tocar ASR streaming (fase 2, queda fuera).

ARCHIVOS CLAVE: kateto/providers/ (providers OpenAI-compatibles, _models.py con max_tokens), kateto/voices/base.py (VoiceAgent._stream_response, token_queue, dict global _PIPELINES), kateto/plugins/audio_output/zonos.py (consume token_queue, síntesis por token — bug 60), kateto/plugins/audio_output/player.py (mixer pcm_queue), kateto/core/event.py (contratos — no romper). Mirá cómo se conecta el TTS hoy: el pipeline es dict global _PIPELINES en base.py con token_queue y pcm_queue.

CONVENCIONES:
- Config: TOML, user config en ~/.config/kateto es autoritativa — NO tocarla. Leer con tomllib.
- Ponytail: solución MÁS SIMPLE que funcione. No construyas una abstracción de TTS nueva: adaptá lo que hay para que reciba frases. Simplificaciones con `# ponytail: motivo`.
- NO commitees. Dejá los cambios en el working tree.
- NO toques archivos fuera del scope. NO reformatees código ajeno.

TESTS:
- `uv run pytest kateto/tests/<tus tests> -x -q` (pytest-asyncio strict: marcar @pytest.mark.asyncio).
- Failures PRE-EXISTENTES conocidos (test_tui tab mismatch, kateto.qa missing, test_conversation_support, test_space_*): NO los toques.
- Prior art: kateto/tests/test_audio_output_plugins.py (ojo: tenía un SyntaxError histórico — verificá si está sano hoy), tests de voices.

REPORTÁ al final: archivos cambiados, tests corridos y resultado, y CÓMO se prueba esta feature de forma REAL en el runtime (no tests).
