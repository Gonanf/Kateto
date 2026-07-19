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

## Resueltos (✅)

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

---

## Cómo reportar un issue

1. Crear archivo en `docs/bugs/` con formato `NN-descripcion-breve.md`
2. Incluir: severidad, componente, descripción, impacto, causa, solución propuesta
3. Actualizar este índice
