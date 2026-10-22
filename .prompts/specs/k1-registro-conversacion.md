# k1 — Registro completo: qué dijo el usuario, qué respondió el agente, qué decidió el clasificador

**Repo:** `~/proyectos/OpenaiBuildWeek/Kateto` · **rama actual:** `fix/jaw-snap-idle`
**Árbol sucio:** hay 43 archivos sin commitear. **Creá SÓLO archivos nuevos.** Si necesitás tocar un
archivo existente, hacé el cambio MÍNIMO y listalo aparte en el reporte con el motivo.

## Meta (una sola)
Un plugin nuevo, `conversation_log`, que deje TODO lo que pasa en la conversación en un log
append-only por sesión: lo que dijo el usuario (transcripción), lo que respondió el agente
(`TextChunk` final), lo que **decidió el clasificador**, más tools y errores.

## Anclas — no explores (REGLA 0)
Abrí SOLO estos archivos:
- `kateto/plugins/executor/memory_sink_plugin.py` — **el patrón a copiar**: es un `Plugin` con
  handlers `on_transcription`, `on_text_chunk`, `on_tool_result`, `on_generate` (ya resuelve
  `config_dir`, el fallback y el logging).
- `kateto/core/event.py` — los contratos, en estas líneas exactas:
  - `:52 TranscriptionData` → `text`, `language`, `confidence`, `duration_ms`
  - `:99 ClassificationData` → `text`, `category`, `confidence`, `voice`, `workflow`, `project_state`
  - `:113 TextChunk` → `text`, `sequence`, `final`, `voice_id`
  - `:277 ToolCallData`, `:284 ToolResultData`, `:170 PluginErrorData`
  - y `EventEnvelope(name, data, source, timestamp, target, capabilities, only_once)` para saber qué
    trae el `envelope` que reciben los handlers.
- `kateto/core/plugin.py` (la clase base) y `kateto/core/discovery.py` (cómo se descubren y habilitan
  los plugins; `live.py:34` llama a `discover_plugins`).
- Los tests que ya existen de un plugin del executor, para copiar el estilo (BDD: `# Given/When/Then`,
  `pytest-asyncio` en strict mode, `tmp_path`).

## Diseño — decidido, no lo inventes
- Archivo: `<config_dir>/logs/session-YYYY-MM-DD.jsonl` — `config_dir` es el mismo que resuelve
  `MemorySinkPlugin` (o sea `~/.config/kateto`). Un JSON por línea, append, UTF-8,
  `ensure_ascii=False`. Rotación por día en el nombre del archivo.
- Nombre del plugin: `conversation_log`, capabilities `("logging", "conversation_log")`.
- Una línea por evento, con estos campos fijos:
  `ts` (ISO 8601 con offset local), `epoch` (float), `event`
  (`user_turn|voice_turn|classifier|tool_call|tool_result|error`), `source` (el `source` del
  envelope), `voice`, `text`, `extra` (dict).
- `extra` según el evento: transcripción → `language`, `confidence`, `duration_ms`; clasificador →
  `category`, `confidence`, `workflow`, `project_state`; tools → nombre, args / ok.
- `text` truncado a **4000 caracteres** por línea. Nada de saltos de línea reales dentro de un JSON.
- **Nunca bloquea el bus**: si la escritura falla (permisos, disco), `logger.warning` y seguir. Una
  excepción acá no puede tumbar el runtime.
- `TextChunk` se registra **sólo con `final=True`** (los parciales son ruido).

## Lo que NO hay que tocar
- No cambies los contratos de `core/event.py` ni el `PluginManager` ni `live.py` (salvo que el
  descubrimiento exija una línea; si es así, decilo).
- No toques `memory_sink_plugin.py`, el clasificador, ni la config de las voces.
- No agregues dependencias nuevas (nada de pandas, nada de chromadb).
- No escribas en `~/.config/kateto` real desde los tests: usá `tmp_path`.
- **No commitees ni pushees.**

## Tests (`kateto/tests/test_conversation_log.py`, pytest-asyncio)
- `on_transcription` con un `TranscriptionData` → una línea `user_turn` con el texto.
- `on_text_chunk` con `final=True` → una línea `voice_turn`; con `final=False` → **no** escribe.
- `on_classification` (el evento de `ClassificationData`) → línea `classifier` con `category` y
  `confidence`.
- `on_tool_call` / `on_tool_result` / `on_error` → sus líneas.
- Un handler con un objeto raro (sin `.text`) no explota ni escribe basura.
- El archivo resultante tiene **todas las líneas parseables con `json.loads`**.
- Cada test escribe en su `tmp_path`; nunca en el config real.

## Gates (correlos y pegá la salida CRUDA)
```bash
cd ~/proyectos/OpenaiBuildWeek/Kateto
uv run pytest kateto/tests/test_conversation_log.py -q
uv run pytest -q 2>&1 | tail -6      # baseline vs después
```
**Baseline conocido** (de `AGENTS.md`, no lo re-investigues): 7 archivos de test con error de
colección por falta del módulo `kateto.qa`, más `test_cli_connector` y `test_conversation_support`.
Corré la suite COMPLETA antes de tocar nada y pegá el conteo; después volvé a correrla y pegá el
conteo otra vez. Si aparece un bug de los que no son tuyos, documentalo como pide `AGENTS.md`
(`docs/src/content/docs/bugs/NN-*.md`) — pero eso va como tarea aparte, no lo mezcles en este cambio.

## Reporte — `/home/chaos/harness-run/k1/REPORT.md` (ruta ABSOLUTA)
1. Archivos creados/tocados, `archivo:línea`, con el diseño del JSONL pegado.
2. Salida CRUDA de los gates (antes y después).
3. Qué quedó sin hacer, qué viste y no tocaste, y qué archivo existente tuviste que tocar y por qué.
