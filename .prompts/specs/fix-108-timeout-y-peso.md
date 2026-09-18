# Visión: el describe tarda más que el timeout de 30 s del cliente MCP (y recién ahí la narración)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"se tomó 4 minutos en empezar, en vez de los 30 segundos que puse. con un error de MCP tool timed out"

## Evidencia (medida, no hipótesis)
1. **El cliente MCP corta a los 30 s, hardcodeado**: `kateto/plugins/system/external_mcp.py::call_tool_result`
   (`asyncio.wait_for(..., timeout=30.0)`). Reproducido con el cliente REAL de Kateto
   (`ExternalMcpClient`, binario y args del config del usuario: `/home/study/.local/bin/video-rag mcp serve`):
   ```
   start(): 0.05s   last_error=None
   tools: ['search', 'list_videos', 'describe', 'describe_images', 'answer', 'summarize']
     [8x8]               10.55s  is_error=False  text='La imagen que has proporcionado es completamente roja...'
     [1920x1080 con texto] 30.03s  is_error=True  text='{"error": "MCP tool timed out: describe_images"}'
   ```
   O sea: un frame de 1920x1080 **no alcanza a terminar en 30 s** y el cliente corta. Ese texto de 48 chars
   es exactamente el que aparece en el log del runtime del usuario.
2. **Por qué tarda tanto**: en el log del VLM (`/var/log/llama-server.log`, alias `LFM2.5-VL-3B`, Q4_K_M):
   ```
   slot print_timing: id 0 | task 259 | prompt processing, n_tokens = 1319, progress = 0.56, t = 20.00 s / 65.95 tokens per second
   ```
   una sola imagen de pantalla ≈ 2350 tokens de visión y el prefill va a ~66 tok/s ⇒ ~36 s sólo de prefill,
   más la generación. Con 3 frames en la ventana, peor. El `mcp` del usuario manda la captura en resolución
   nativa.
3. **Consecuencia en su runtime** (log, líneas textuales): el job corre cada 30 s, el describe muere por
   timeout y la narración se suprime:
   ```
   [scheduler] job vision-describe-jane registered: vision_describe_request every 0:00:30 (target=jane)
   [scheduler] job vision-describe-jane fired -> vision_describe_request
   [vision] sidecar describe_images answered (48 chars): {"error": "MCP tool timed out: describe_images"}
   [vision] periodic narration suppressed for jane: no real description (via=recap)
   ```
   ⇒ el usuario percibe "no se ejecuta" (nadie habla), aunque el job sí dispara.

## Fix esperado
1. **Timeout configurable y más largo para la visión.**
   - `call_tool_result`/`call_tool` tienen que aceptar un `timeout` por llamada (default el de hoy, sin
     romper a nadie).
   - La visión pasa su propio timeout: el que ya existe en config (`executor_vision.vision_timeout`,
     hoy 60.0) o `max(vision_timeout, 120)`; dejalo documentado y logueado cuando se usa.
   - El timeout tiene que cubrir también el arranque en frío del VLM: un `vision_timeout` de 60 s puede
     quedar corto, así que el default de la visión debería ser ≥120 s y configurable.
2. **Bajar el costo por frame: recomprimir antes de mandar** (esto es lo que hacía fix-104, ahora con esta
   razón, que es la importante — latencia, no sólo el tope de 1.5 MB):
   - JPEG/WebP con ancho máximo configurable (default 1280 px, aspecto preservado) y calidad razonable;
   - objetivo: un frame real de 1920x1080 tiene que bajar a ~1/3 o menos de los tokens actuales;
   - si el data-URL resultante no entra en el tope del sidecar (~1.5 MB), bajar calidad/escala y, si no
     entra, descartar el frame con log (nunca mandar algo que el sidecar va a rechazar).
   - PIL ya está en las deps de visión; no agregues dependencias.
3. **Acotar cuántos frames van por describe.** Cada frame cuesta ~2350 tokens de visión: mandar 3-5
   frames multiplica el prefill (105+ s medidos por extrapolación). Para la narración periódica alcanza
   con 1-2 frames (el más viejo de la ventana y el más nuevo, que es lo que muestra el cambio); dejalo
   configurable (p.ej. `max_frames_per_describe`, default 2) y documentá el motivo con estos números.
   Que el log diga cuántos frames se mandaron.
4. **Precalentamiento del VLM** cuando arranca la visión periódica (si hay endpoint VLM configurado o
   sidecar): un describe mínimo (imagen 1x1) para que el primer tick real no pague la carga del modelo.
   Tiene que ser best-effort: si falla, se loguea y no rompe nada.
4. **Un timeout no es una descripción** (ya cubierto por fix-102/106: `is_error` y formas de error): que
   la narración no lo emita y que el motivo quede logueado completo. Verificá que el camino nuevo del
   timeout por llamada siga marcando `is_error=True`.

## Tests (obligatorios)
- `call_tool_result(timeout=...)` respeta el timeout pasado (un fake que tarda más ⇒ error de timeout).
- La visión pasa su timeout configurado (no el 30 s fijo) y lo loguea.
- Un frame sintético de 1920x1080 ⇒ el data-URL que se manda al sidecar baja de tamaño respecto del
  original (y sigue siendo una imagen válida, con el aspecto preservado y el ancho máximo respetado).
- Un frame chico no se agranda ni se reencoda al pedo.
- El precalentamiento es best-effort: si el describe mínimo falla, no rompe el arranque ni genera error
  visible para el usuario.
- Los tests existentes de visión/MCP siguen verdes.

## Docs
- Bug nuevo (id siguiente): "el describe de una captura real supera el timeout de 30 s del cliente MCP:
  la narración llega tarde y con un error de timeout" — con los números medidos (n_tokens ≈ 1300,
  ~66 tok/s, timeout 30 s).
- `known-issues.md` + `plugins/vision.md` (documentar timeout y recompresión).

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or mcp"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **510 passed / 3 failed** (preexistentes) más
   lo que sumen fix-103/107; compará contra esos 3 fallos
3. `git diff --stat`
4. Si podés: medir el data-URL antes/después para 1920x1080 y dejarlo en el resumen.

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Cambiar la resolución de *captura*
  (el ajuste va antes de mandar). Elegir modelos.
