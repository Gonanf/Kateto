---
id: 115
title: "Config por voz pisa al principal en silencio y el recap hace hablar a la voz cada 30 s"
severity: Alta
status: resolved
component: kateto/core/config.py, kateto/plugins/executor/static_vision_plugin.py, kateto/plugins/system/external_mcp.py
resolved: 2026-09-18
---

## 115. Config por voz pisa al principal en silencio y el recap hace hablar a la voz cada 30 s

**Severidad:** Alta
**Componente:** `kateto/core/config.py`, `kateto/plugins/executor/static_vision_plugin.py`, `kateto/plugins/system/external_mcp.py`

### Descripción

Cadena completa medida en runtime real: `voices/jane/config.toml` tenía
`vision_periodic = true`, `skills = ["orchestrator"]` y `mcp_servers = ["system"]`,
mientras el `config.toml` principal decía `vision_periodic = false`,
`skills = ["orchestrator","look-at"]` y `mcp_servers = ["system","video_rag"]`.
`_load_voice_folder_configs` fusiona con `{**existing, **vsettings}`: el archivo
por voz gana **en silencio**. Consecuencias encadenadas: la narración ambiental
seguía prendida, la voz no tenía la skill `look-at`, el cliente MCP `video_rag`
no existía (de ahí el "sidecar unreachable"), el describe caía al `recap`… y el
camino periódico igual emitía el `generate` de narración, así que la voz hablaba
sola cada 30 s con un texto que no describía nada ("la visión no está configurada").

### Impacto

Voz hablando sola cada 30 s; `look-at` roto; una tarde de diagnóstico perdida
porque el motivo real del sidecar ("sin cliente" vs "sin tool") se mezclaba en
un solo mensaje.

### Causa

1. Precedencia silenciosa del archivo por voz sobre `[voice] <voz>.*` del principal.
2. El tick periódico narraba también con `via=recap`.
3. `_describe_fallback` logueaba "no client or no describe_images tool" sin
   distinguir, y `ExternalMcpManager` no conservaba el motivo del arranque fallido.

### Solución aplicada

- `config.py`: cada clave pisada deja un `warning` con clave, valor del principal,
  valor del archivo y archivo ganador (visible con `log_level = INFO`); las notas
  quedan en `get_voice_override_notes()` / `get_voice_file_sources()` y
  `kateto config check` muestra los valores efectivos por voz con su fuente.
  Semántica intacta: el archivo por voz sigue ganando.
- `static_vision_plugin.py`: con `via=recap` el tick periódico no emite `generate`
  (un warning la primera vez, `debug` después); el pedido directo del usuario sí
  contesta; con `via` real la narración sigue igual.
- `external_mcp.py`: `ExternalMcpClient.last_error` conserva el fallo de arranque;
  `ExternalMcpManager.sidecar_reason()` distingue "sin cliente configurado" de
  "cliente corriendo sin la tool", y el fallback loguea ese motivo.

**Regresión:** `kateto/tests/test_vision_precedence_recap.py` (6 tests);
`test_periodic_scheduler_request_emits_targeted_generate` ahora configura
endpoint+modelo para que el describe sea real (`via=primary`).

**Archivos:** `kateto/core/config.py`, `kateto/cli/commands.py`,
`kateto/plugins/executor/static_vision_plugin.py`, `kateto/plugins/system/external_mcp.py`,
`kateto/tests/test_vision_precedence_recap.py`, `kateto/tests/test_vision_lifecycle.py`
