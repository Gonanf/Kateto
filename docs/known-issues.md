# Problemas Conocidos (Known Issues)

> Fecha: Noviembre 2026 · Compilado durante análisis post-MVP
> Cada bug tiene su propio archivo en [`docs/bugs/`](./bugs/) con detalle completo.

---

## Abiertos

| # | Bug | Severidad | Componente | Archivo |
|---|-----|-----------|------------|---------|
| 1 | whisper-server no usa GPU correctamente | Media | `providers/whisper.py` | [01-whisper-gpu.md](./bugs/01-whisper-gpu.md) |
| 2 | Sin tests end-to-end | Media | `kateto/tests/` | [02-no-e2e-tests.md](./bugs/02-no-e2e-tests.md) |
| 7 | Proyecto no runneable sin configuración externa | Alta | `README.md`, `config/defaults/` | [07-not-runnable.md](./bugs/07-not-runnable.md) |
| 12 | TODO.md se escribe en voices/shared/ | Informativa | `plugins/executor/todo_list.py` | [12-todo-md-location.md](./bugs/12-todo-md-location.md) |
| 26 | CLI smoke apunta a scripts/qa eliminado | Media | `kateto/__main__.py`, `script/qa` | [26-smoke-cli-deleted-qa-path.md](./bugs/26-smoke-cli-deleted-qa-path.md) |


## Resueltos (✅)

| # | Bug | Severidad | Componente | Archivo |
|---|-----|-----------|------------|---------|
| 28 | Workflow de proyecto nuevo no se inicia y TUI filtra eventos | Alta | `classifier.py`, `tui.py` | [28-workflow-discovery-and-tui-event-filter.md](./bugs/28-workflow-discovery-and-tui-event-filter.md) |
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

---

## Cómo reportar un issue

1. Crear archivo en `docs/bugs/` con formato `NN-descripcion-breve.md`
2. Incluir: severidad, componente, descripción, impacto, causa, solución propuesta
3. Actualizar este índice
