---
title: "Known Issues"
description: "Known Issues — índice de bugs"
---

# Problemas Conocidos (Known Issues)

> Fecha: Noviembre 2026 · Compilado durante análisis post-MVP
> Cada bug tiene su propio archivo en [`docs/bugs/`](./bugs/) con detalle completo.

---

## Abiertos

| # | Bug | Severidad | Componente | Archivo |
|---|-----|-----------|------------|---------|
| 2 | Sin tests end-to-end | Media | `kateto/tests/` | [02-no-e2e-tests.md](./bugs/02-no-e2e-tests.md) — **parcialmente resuelto 2026-08-25**: e2e de workflows+tool-calling en `test_workflow_e2e.py`, autonomía en `test_autonomy_e2e.py`; el pipeline completo de audio real sigue sin cobertura |
| 7 | Proyecto no runneable sin configuración externa | Alta | `README.md`, `config/defaults/` | [07-not-runnable.md](./bugs/07-not-runnable.md) |
| 12 | TODO.md se escribe en voices/shared/ | Informativa | `plugins/executor/todo_list.py` | [12-todo-md-location.md](./bugs/12-todo-md-location.md) |


## Resueltos (✅)

| # | Bug | Severidad | Componente | Archivo |
|---|-----|-----------|------------|---------|
| 1 | whisper-server no usa GPU correctamente | Media | `kateto/providers/whisper.py` | [01-whisper-gpu.md](./bugs/01-whisper-gpu.md) |
| 61 | SchedulerPlugin nunca se ensambla en el runtime y dispara payloads dict que el bus rechaza | Alta | `plugins/executor/__init__.py`, `plugins/executor/scheduler.py` | [61-scheduler-never-wired-and-dict-payload-crash.md](./bugs/61-scheduler-never-wired-and-dict-payload-crash.md) |
| 28 | Workflow de proyecto nuevo no se inicia y TUI filtra eventos | Alta | `classifier.py`, `tui.py` | [28-workflow-discovery-and-tui-event-filter.md](./bugs/28-workflow-discovery-and-tui-event-filter.md) |
| 26 | CLI smoke apunta a scripts/qa eliminado | Media | `kateto/cli/commands.py` | [26-smoke-cli-deleted-qa-path.md](./bugs/26-smoke-cli-deleted-qa-path.md) |
| 53 | Voz falla en generate: list_events revienta con anotaciones UnionType | Alta | `kateto/voices/tools.py` | [53-list-events-uniontype-crash.md](./bugs/53-list-events-uniontype-crash.md) |
| 54 | KatetoToolset envía herramientas con esquemas de parámetros vacíos | Alta | `kateto/voices/tools.py` | [54-kateto-toolset-empty-schemas.md](./bugs/54-kateto-toolset-empty-schemas.md) |
| 55 | DiskMediaStore object is not callable en capacidades de VoiceAgent | Alta | `kateto/voices/factory.py` | [55-diskmediastore-not-callable.md](./bugs/55-diskmediastore-not-callable.md) |
| 56 | WebSearch y WebFetch fallan con UserError en OpenAIChatModel | Alta | `kateto/voices/factory.py` | [56-websearch-webfetch-unsupported-openaichatmodel.md](./bugs/56-websearch-webfetch-unsupported-openaichatmodel.md) |
| 29 | Workflow inicia sin generar instrucciones para su voz propietaria | Alta | `core/workflow_engine.py` | [29-workflow-no-owner-generation.md](./bugs/29-workflow-no-owner-generation.md) |
| 30 | Solicitud de nuevo proyecto selecciona un workflow no relacionado | Alta | `plugins/executor/workflow_router.py` | [30-new-project-workflow-selection.md](./bugs/30-new-project-workflow-selection.md) |
| 31 | Follow-up reemplaza el workflow activo y pierde el contexto de fase | Alta | `core/workflow_engine.py`, `plugins/executor/workflow_router.py` | [31-active-workflow-switch-and-interrupt.md](./bugs/31-active-workflow-switch-and-interrupt.md) |
| 32 | El agente no completa fases ni entregables del workflow | Alta | `voices/base.py`, `voices/tools.py` | [32-workflow-does-not-advance.md](./bugs/32-workflow-does-not-advance.md) |
| 33 | Workflow omite una voz llamada que está deshabilitada | Alta | `core/workflow_engine.py`, `run_mode.py` | [33-disabled-called-voice.md](./bugs/33-disabled-called-voice.md) |
| 34 | Voz no responde después de tool calls | Alta | `kateto/voices/base.py` | [34-agent-silent-after-tool-call.md](./bugs/34-agent-silent-after-tool-call.md) |
| 35 | Voz activada dinámicamente sigue apareciendo deshabilitada | Alta | `kateto/run_mode.py` | [35-dynamic-voice-stays-disabled.md](./bugs/35-dynamic-voice-stays-disabled.md) |
| 36 | Fixture TUI inicia sin respuestas ni workflows | Alta | `kateto/plugins/system/tui.py` | [36-fixture-tui-no-runtime.md](./bugs/36-fixture-tui-no-runtime.md) |
| 37 | Fixture voices use identical response behavior | Media | `kateto/plugins/system/tui.py` | [37-fixture-voices-identical.md](./bugs/37-fixture-voices-identical.md) |
| 38 | Doktor falla en generate — 'dict' no tiene conversation_id | Alta | `kateto/voices/base.py` | [38-doktor-generate-dict-conversation_id.md](./bugs/38-doktor-generate-dict-conversation_id.md) |
| 27 | TUI se congela durante streaming de TTS y eventos de audio | Crítica | `tui.py`, `edgetts.py`, `player.py`, `whisper.py` | [27-tui-freeze-tts-streaming.md](./bugs/27-tui-freeze-tts-streaming.md) |
| 25 | Web sandbox: presentación interactiva del sistema Kateto | Media | `web/` (nuevo) | [25-web-sandbox-presentation.md](./bugs/25-web-sandbox-presentation.md) |
| 24 | TUI: conflictos de nombres entre voces activadas y plugins auto-detectados | Media | `kateto/plugins/system/tui.py` | [24-tui-voice-name-conflict.md](./bugs/24-tui-voice-name-conflict.md) |
| 23 | Nuevo plugin VoiceSOULManager: gestión centralizada de SOUL/JOURNAL/workflows | Media | `kateto/plugins/voice_soul_manager/` | [23-plugin-soul-journal-manager.md](./bugs/23-plugin-soul-journal-manager.md) |

| # | Bug | Severidad | Componente | Archivo |
|---|-----|-----------|------------|---------|
| 3 | CallbackQueue con capacity fijo en 32 | Baja | `plugins/audio_input/base.py` | [03-callbackqueue-capacity.md](./bugs/03-callbackqueue-capacity.md) |
| 4 | Plugins sin isolation de errores | Alta | `core/manager.py` | [04-plugin-error-isolation.md](./bugs/04-plugin-error-isolation.md) |
| 5 | Sin logging estructurado | Media | `voices/base.py` | [05-no-structured-logging.md](./bugs/05-no-structured-logging.md) |
| 6 | Hot-reload sin test coverage | Media | `core/hot_reload.py` | [06-hot-reload-test-coverage.md](./bugs/06-hot-reload-test-coverage.md) |
| 8 | Hot reload cancela workers durante LLM calls | Crítica | `core/hot_reload.py` | [08-hot-reload-cancels-workers.md](./bugs/08-hot-reload-cancels-workers.md) |
| 9 | List plugins response lost in text_chunk | Baja | `voices/base.py` | [09-text-chunk-capture.md](./bugs/09-text-chunk-capture.md) |
| 10 | Voices no se pueden habilitar/deshabilitar en runtime | Alta | `voices/factory.py` | [10-runtime-voice-enable.md](./bugs/10-runtime-voice-enable.md) |
| 11 | backlog_list sin filtro por prioridad | Baja | `core/event.py` | [11-backlog-priority-filter.md](./bugs/11-backlog-priority-filter.md) |
| 13 | Archivos y carpetas duplicados | Alta | Estructura del proyecto | [13-duplicated-files.md](./bugs/13-duplicated-files.md) |
| 14 | Sin herramientas runtime para Skills/Workflows/Voces | Media | `voices/tools.py` | [14-no-runtime-tools.md](./bugs/14-no-runtime-tools.md) |
| 15 | Hot reload reemplaza todos los plugins sin verificar cambio | Crítica | `core/hot_reload.py` | [15-hot-reload-unnecessary-replacement.md](./bugs/15-hot-reload-unnecessary-replacement.md) |
| 16 | TUI plugins tab: test con botones enable/disable inexistentes | Media | `tests/test_tui.py` | [16-tui-plugin-toggle.md](./bugs/16-tui-plugin-toggle.md) |
| 17 | TUI: Switch de plugins no visible, voces deshabilitadas no aparecen en tree | Media | `tui.py`, `tests/test_tui.py`, `run_mode.py` | [17-tui-plugin-switch-voice-visibility.md](./bugs/17-tui-plugin-switch-voice-visibility.md) |
| 18 | TUI usa `Path.cwd()` como config_dir, ignorando user config y reactivando duplicados | Crítica | `tui.py` | [18-tui-cwd-config-priority.md](./bugs/18-tui-cwd-config-priority.md) |
| 19 | `_agent_loop` no hace streaming aunque `stream=true` en config | Alta | `base.py`, `agent.py`, `factory.py` | [19-agent-loop-no-stream.md](./bugs/19-agent-loop-no-stream.md) |
| 20 | TUI events tab: autocomplete genera JSON multilinea que rompe el Input | Media | `tui.py` | [20-tui-autocomplete-multiline-json.md](./bugs/20-tui-autocomplete-multiline-json.md) |
| 21 | TUI conversation tab: todas las respuestas de una voz se escriben en la primera burbuja | Media | `tui.py` | [21-tui-conversation-single-bubble.md](./bugs/21-tui-conversation-single-bubble.md) |
| 22 | config/defaults/voices/ no incluye SOUL.md para jane, doktor, conquest | Media | `config/defaults/voices/` | [22-default-voices-no-soul.md](./bugs/22-default-voices-no-soul.md) |
| 62 | Camb AI TTS reproduce audio duplicado por re-emisión de la respuesta final acumulada | Media | `voices/base.py`, `plugins/audio_output/camb.py` | [62-cambai-tts-repetition.md](./bugs/62-cambai-tts-repetition.md) |
| 63 | PortAudio ALSA xrun y crash por aserción self->neverDropInput al abrir y cerrar streams concurrentes | Alta | `plugins/audio_output/player.py`, `plugins/audio_input/capture.py` | [63-portaudio-alsa-assertion-crash.md](./bugs/63-portaudio-alsa-assertion-crash.md) |
| 64 | Fallo de validación Pydantic en WhisperResponse ante silencios o ruido ambiente sin habla | Media | `providers/_models.py`, `plugins/audio_processor/whisper.py` | [64-whisper-empty-speech-validation.md](./bugs/64-whisper-empty-speech-validation.md) |
| 65 | Desincronización de subtítulos con el audio TTS por emisión prematura de tokens LLM | Media | `plugins/visual_overlay/visual_overlay_plugin.py`, `web/index.html` | [65-subtitle-desynchronization-tts.md](./bugs/65-subtitle-desynchronization-tts.md) |
| 66 | AttributeError en WhisperProvider por atributo _settings no inicializado al consultar language | Alta | `providers/whisper.py` | [66-whisper-provider-missing-settings.md](./bugs/66-whisper-provider-missing-settings.md) |
| 67 | Comando debate ignora configuración de voice_llm por type-check y hardcodea modelo KatetoTalker | Alta | `kateto/cli/commands.py` | [67-debate-hardcoded-katetotalker.md](./bugs/67-debate-hardcoded-katetotalker.md) |
| 68 | Debate CLI sin límite max_tokens, advertencia de tareas sin cerrar en ^C y estado del courtroom desconectado | Media | `kateto/cli/commands.py`, `kateto/plugins/visual_overlay/` | [68-debate-hang-tts-courtroom-state.md](./bugs/68-debate-hang-tts-courtroom-state.md) |
| 69 | Debate TTS: SIGSEGV en interrupciones PortAudio, concurrencia en Camb.ai, delays inflados y omisión de SOUL.md | Alta | `plugins/audio_output/`, `plugins/bate_debate/` | [69-debate-tts-concurrency-and-timing.md](./bugs/69-debate-tts-concurrency-and-timing.md) |
| 70 | Restauración del Visual Overlay básico y resiliencia del estado de interrupción en AudioPlayer y Camb.ai | Alta | `visual_overlay/`, `audio_output/` | [70-overlay-restoration-and-tts-resilience.md](./bugs/70-overlay-restoration-and-tts-resilience.md) |
| 71 | Refactorización de bate_debate al bus nativo de eventos de Kateto y preservación de SOUL.md | Alta | `bate_debate/`, `voices/base.py`, `providers/agent.py` | [71-debate-event-bus-refactoring-and-soul-preservation.md](./bugs/71-debate-event-bus-refactoring-and-soul-preservation.md) |
| 72 | Configuración por carpeta de voz y registro dinámico de parámetros de plugins | Media | `core/config.py`, `plugins/audio_output/boson_tts_plugin.py` | [72-voice-folder-config-and-dynamic-plugin-params.md](./bugs/72-voice-folder-config-and-dynamic-plugin-params.md) |
| 73 | Debate TTS repetición de voz en navegador y TimeoutError en generate_turn | Alta | `bate_debate/orchestrator.py`, `web/courtroom.html` | [73-debate-tts-repetition-and-timeout.md](./bugs/73-debate-tts-repetition-and-timeout.md) |
| 74 | Bate debate: solapamiento prematuro de oradores y voces en tercera persona o eco textual | Alta | `bate_debate/orchestrator.py` | [74-debate-speaker-overlap-and-voice-echo-third-person.md](./bugs/74-debate-speaker-overlap-and-voice-echo-third-person.md) |
| 75 | Visual overlay: soporte para reproducción de audio TTS en navegador y layout multi-agente configurable | Media | `plugins/visual_overlay/` | [75-overlay-tts-audio-streaming-and-multi-agent-layout.md](./bugs/75-overlay-tts-audio-streaming-and-multi-agent-layout.md) |
| 76 | Visual overlay: filtrado estricto por ventana y posicionamiento programático para juegos (Chess/Versus/Sides) | Media | `plugins/visual_overlay/` | [76-overlay-strict-voice-filter-and-game-positioning.md](./bugs/76-overlay-strict-voice-filter-and-game-positioning.md) |
| 77 | OpenAI-compatible API Server: interfaz HTTP /v1/chat/completions sobre el bus de eventos de Kateto | Media | `plugins/system/openai_server.py` | [77-openai-compatible-api-server-over-event-bus.md](./bugs/77-openai-compatible-api-server-over-event-bus.md) |
| 78 | Debate TTS double speech y corte instantáneo de audio en interrupciones con EdgeTTS | Alta | `plugins/system/http_server.py`, `plugins/audio_output/` | [78-debate-tts-double-speech-and-interrupt-cutoff.md](./bugs/78-debate-tts-double-speech-and-interrupt-cutoff.md) |
| 79 | Barrera wait_idle en Plugin y sincronización determinista de turnos de voz TTS | Alta | `core/plugin.py`, `plugins/audio_output/` | [79-plugin-wait-idle-tts-turn-synchronization.md](./bugs/79-plugin-wait-idle-tts-turn-synchronization.md) |
| 80 | Streaming PCM chunked en EdgeTTS e interrupción por cue implantado en objeciones | Media | `plugins/audio_output/edgetts.py`, `plugins/bate_debate/` | [80-edgetts-pcm-streaming-and-implanted-objection-cue.md](./bugs/80-edgetts-pcm-streaming-and-implanted-objection-cue.md) |
| 81 | PortAudio ALSA assertion crash, stream persistence and debate turn pacing | Alta | `plugins/audio_output/player.py`, `plugins/audio_output/edgetts.py`, `plugins/bate_debate/` | [81-portaudio-stream-persistence-and-debate-turn-pacing.md](./bugs/81-portaudio-stream-persistence-and-debate-turn-pacing.md) |
| 82 | Interrupción de voz global mutando al siguiente orador y deadlock en feed de FFmpeg | Alta | `plugins/audio_output/edgetts.py`, `providers/edgetts.py`, `plugins/bate_debate/` | [82-scoped-interruption-and-ffmpeg-feed-pipeline.md](./bugs/82-scoped-interruption-and-ffmpeg-feed-pipeline.md) |
| 83 | Interrupción fantasma en http_server silenciando la objeción entrante | Crítica | `plugins/system/http_server.py` | [83-http-server-phantom-interrupt-on-objection.md](./bugs/83-http-server-phantom-interrupt-on-objection.md) |
| 84 | Stream de PortAudio inactivo tras stream.abort() silenciando todo audio posterior | Crítica | `plugins/audio_output/player.py` | [84-portaudio-stream-reactivation-after-abort.md](./bugs/84-portaudio-stream-reactivation-after-abort.md) |
| 85 | Fuga de bandera _playing en EdgeTTS causando congelamiento de 45s en wait_idle | Crítica | `plugins/audio_output/edgetts.py`, `plugins/bate_debate/` | [85-edgetts-playing-flag-leak-and-wait-idle-stall.md](./bugs/85-edgetts-playing-flag-leak-and-wait-idle-stall.md) |
| 86 | ALSA mmap xrun en streams persistentes y demora artificial en cue de objeción | Crítica | `plugins/audio_output/player.py`, `plugins/bate_debate/` | [86-alsa-mmap-xrun-and-stream-lifecycle.md](./bugs/86-alsa-mmap-xrun-and-stream-lifecycle.md) |

---

## Cómo reportar un issue

1. Crear archivo en `docs/bugs/` con formato `NN-descripcion-breve.md`
2. Incluir: severidad, componente, descripción, impacto, causa, solución propuesta
3. Actualizar este índice
