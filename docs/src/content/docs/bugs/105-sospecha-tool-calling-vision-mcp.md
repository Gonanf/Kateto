---
id: 105
title: "Sospecha sin confirmar: el problema restante puede estar en el tool calling (visión/MCP)"
severity: Media
status: open
component: kateto/voices/tools.py, kateto/plugins/system/external_mcp.py
---

## 105. Sospecha sin confirmar: el problema restante puede estar en el tool calling (visión/MCP)

**Severidad:** Media
**Componente:** `kateto/voices/tools.py`, `kateto/plugins/system/external_mcp.py`

### Descripción

Reporte del usuario (2026-09-17): tras la tanda de fixes de visión/audio, "ahora está arreglado creo, pero el problema puede estar en el tool calling". Sin.tw confirmar: con el sidecar `video-rag` corriendo y las voces con `video_rag` en `mcp_servers`, está por verificar que el modelo (a) reciba las tools MCP en su lista (`_sync_external_tools` → `add_extra_tools`), (b) las invoque (`describe_images`/`search`/`answer`) y (c) consuma los resultados.

### Impacto

Si el tool calling falla, el modelo sigue sin "ver" aunque todo el plumbing exista.

### Posible solución

1. Reiniciar con el código actual y verificar en el log `External MCP 'video_rag' started` + tools inyectadas.
2. Pedir explícitamente al modelo que use una tool de video_rag y observar `ToolCallData`/`ToolResultData` en el log.
3. Si no las llama: revisar `get_tools_for`/`add_extra_tools` y el `ToolSearch` capability; si las llama y falla: revisar `try_call_tool` y el parsing de resultados.

**Archivos:** `kateto/voices/tools.py`, `kateto/plugins/system/external_mcp.py`, `kateto/run_mode.py`
