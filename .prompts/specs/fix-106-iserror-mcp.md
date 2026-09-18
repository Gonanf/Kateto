# El cliente MCP tira `isError` y por eso un error del sidecar se puede narrar como descripción

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Contexto (ya mergeado, no lo rehagas)
En fix-102 se agregó `_is_sidecar_error()` en `kateto/plugins/executor/static_vision_plugin.py`, que
reconoce **formas** de error (`video-rag describe_images:`, `VLM unreachable`, `{"error"`) y en ese caso
loguea el texto y cae al recap en vez de narrarlo. Eso tapa los dos casos que conocemos, pero es
adivinanza: el sidecar devuelve sus errores como `{"content":[{"type":"text","text":msg}],"isError":true}`
y hay errores que **no** matchean ninguna de esas formas, por ejemplo (textual de `src/mcp.rs`):
- `image {i} exceeds ~1.5MB data-URL cap ({} bytes)`
- `describe_images needs at least one image data-URL`
- `too many images: got N, max is 8 ...`
- `No indexes available; run \`video-rag index\` first.`

Con esos, el plugin **vuelve a tomar el error como caption** y la voz lo narra.

## Causa raíz
`kateto/plugins/system/external_mcp.py::ExternalMcpClient.call_tool` (línea ~84) descarta el flag:

```python
result = await asyncio.wait_for(self._session.call_tool(name, arguments), timeout=30.0)
texts = [c.text for c in result.content if hasattr(c, "text")]
return "\n".join(texts)          # <-- is_error perdido
```

## Fix
1. **Propagar el flag sin romper a nadie.** En `external_mcp.py`:
   - un `@dataclass(frozen=True) ToolCallResult(text: str, is_error: bool, server: str, tool: str)`;
   - `async def call_tool_result(self, server, tool, arguments) -> ToolCallResult` con la lógica real;
   - `call_tool(...)` queda con la MISMA firma y devuelve `result.text` (compatibilidad total: si no hay
     sesión o hay timeout, sigue devolviendo el texto `{"error": ...}` de siempre, pero ahora con
     `is_error=True`).
   - Que el timeout de 30 s y el cliente ausente queden marcados como `is_error=True`.
2. **La visión usa el flag.** `_describe_fallback` llama a `call_tool_result`; si `is_error` es True:
   - NO es una descripción: loguear el motivo **completo** con server y tool
     (`[vision] sidecar describe_images error: {texto}`) y caer al recap (que la narración ambiental ya
     suprime);
   - dejar `_is_sidecar_error()` como red secundaria (no la borres).
3. **Loguear siempre el texto crudo**, aunque parezca descripción válida:
   `log.info("[vision] sidecar describe_images answered ({} chars): {}", len(text), text[:300])`.
   Hoy sólo se loguea la longitud y por eso no sabemos qué error de 48 caracteres se narró en el runtime.
   Si el texto es largo, truncá a 300 en info y mandá el resto a debug.

## Tests (obligatorios)
- `call_tool_result` propaga `is_error=True` (fake de `result.is_error`) y `call_tool` sigue devolviendo
  sólo el texto.
- Timeout del cliente ⇒ `is_error=True` y texto `{"error": "MCP tool timed out: ..."}`.
- Plugin: un resultado con `is_error=True` y texto tipo `image 0 exceeds ~1.5MB data-URL cap (9999999 bytes)`
  ⇒ **no** se usa como descripción (va a recap) y queda logueado el texto.
- Plugin: un caption válido ⇒ `via="sidecar"` y el log incluye el texto.
- La red secundaria sigue andando (un texto con `VLM unreachable` sin flag se detecta igual).
- Los tests existentes de visión/MCP siguen verdes.

## Docs
- Bug 116 (o nuevo, el que corresponda): documentar que el cliente tiraba `isError` y que ahora se
  propaga; mencionar los errores del sidecar que no se detectaban por forma.
- `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or mcp"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **502 passed / 3 failed**
   (preexistentes: `test_audio_capture`, 2× `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Cambiar la firma pública de `call_tool`.
