---
id: 117
title: "El cliente MCP tiraba `isError` y un error del sidecar se narraba como descripción"
severity: Alta
status: resolved
component: kateto/plugins/system/external_mcp.py
resolved: 2026-09-18
---

## 117. El cliente MCP tiraba `isError` y un error del sidecar se narraba como descripción

**Severidad:** Alta
**Componente:** `kateto/plugins/system/external_mcp.py`, `kateto/plugins/executor/static_vision_plugin.py`

### Descripción

En fix-102 se agregó `_is_sidecar_error()` en `static_vision_plugin.py`, que
reconoce **formas** de error (`video-rag describe_images:`, `VLM unreachable`,
`{"error"`) y en ese caso loguea el texto y cae al recap en vez de narrarlo.
Eso tapa los dos casos que conocemos, pero es adivinanza: el sidecar devuelve
sus errores como `{"content":[{"type":"text","text":msg}],"isError":true}` y hay
errores que **no** matchean ninguna de esas formas, por ejemplo (textual de
`src/mcp.rs` del sidecar):

- `image {i} exceeds ~1.5MB data-URL cap ({} bytes)`
- `describe_images needs at least one image data-URL`
- `too many images: got N, max is 8 ...`
- `No indexes available; run \`video-rag index\` first.`

Con esos, el plugin volvía a tomar el error como caption y la voz lo narraba
(como el error de 48 caracteres del runtime del bug 116, que se narró porque
sólo se logueaba la longitud y no el texto).

### Impacto

Ante cualquier error del sidecar fuera de las dos formas conocidas, la
narración ambiental repetía el error como si fuera lo que vio.

### Causa

`ExternalMcpClient.call_tool` descartaba el flag: extraía los textos de
`result.content` y devolvía `"\n".join(texts)`, perdiendo `isError`.

### Solución aplicada

- Nuevo `@dataclass(frozen=True) ToolCallResult(text, is_error, server, tool)`
  en `external_mcp.py`; `call_tool_result()` con la lógica real (acepta
  `is_error`/`isError`, timeout de 30 s y cliente ausente marcados como
  `is_error=True`); `call_tool(...)` con la MISMA firma devuelve
  `result.text` (compatibilidad total); `try_call_tool_result()` a nivel
  manager y `try_call_tool(...)` delegando en él.
- `_describe_fallback` usa `try_call_tool_result` cuando existe (con fallback
  al camino viejo de texto para fakes/contextos sin el método): con
  `is_error=True` el texto NO es descripción — se loguea completo con server
  y tool y se cae al recap; `_is_sidecar_error()` queda como red secundaria.
- El texto crudo del sidecar siempre se loguea
  (`answered (N chars): <texto[:300]>`, resto a debug), así el próximo error
  desconocido queda visible en el log en vez de perderse.

**Regresión:** `kateto/tests/test_mcp_is_error.py` (8 tests: flag propagado +
compat de texto, ok sin flag, timeout, cliente ausente, manager con flag,
error con flag ⇒ recap + log, caption válido ⇒ sidecar + log, red secundaria
sin flag).

**Archivos:** `kateto/plugins/system/external_mcp.py`,
`kateto/plugins/executor/static_vision_plugin.py`,
`kateto/tests/test_mcp_is_error.py`
