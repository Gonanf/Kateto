# Visión: el describe tarda más que el timeout de 30 s del cliente MCP (y recién ahí la narración)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"se tomó 4 minutos en empezar, en vez de los 30 segundos que puse. con un error de MCP tool timed out"

## Evidencia (medida, no hipótesis)
1. **El cliente MCP corta a los 30 s, hardcodeado**: `kateto/plugins/system/external_mcp.py::call_tool`
   (`asyncio.wait_for(..., timeout=30.0)`), y devuelve el texto
   `{"error": "MCP tool timed out: describe_images"}` (47 chars; el log de visión lo reportaba como
   `sidecar describe_images answered (48 chars)` — la cuenta del plugin).
2. **Un frame real de pantalla hace trabajar al VLM mucho más que eso.** En el log del VLM
   (`/var/log/llama-server.log`, alias `LFM2.5-VL-3B`, Q4_K_M, llama-server con `--sleep-idle-seconds 600`):
   ```
   slot print_timing: id 0 | task 259 | prompt processing, n_tokens = 1319, progress = 0.56, t = 20.00 s / 65.95 tokens per second
   ```
   O sea: la imagen se convierte en ~1300–1600 tokens de visión y el prefill va a ~66 tok/s ⇒ **~20-25 s
   sólo de prefill**, más la generación: el total supera los 30 s y el cliente corta antes de obtener el
   caption. Con el modelo frío (se descarga a los 10 min de inactividad) es peor.
3. Los "4 minutos" son eso + la cadencia: el primer tick gasta >30 s, muere por timeout, y el siguiente
   tick recién a los 30 s siguientes; lo que el usuario vio fue el primer caption/error que sobrevivió.
4. La captura queda en resolución nativa (PNG), así que el costo en tokens del VLM lo paga entero.

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
3. **Precalentamiento del VLM** cuando arranca la visión periódica (si hay endpoint VLM configurado o
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
