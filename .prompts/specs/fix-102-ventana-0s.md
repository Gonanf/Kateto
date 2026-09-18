# Visión: el describe termina con ventanas de 0 segundos

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (runtime real del usuario, hoy 16:28)
```
[vision] sidecar describe_images answered (48 chars)
[vision] describe requester=scheduler:jane source=auto via=sidecar frames=1/5 chars=80
[vision] periodic narration -> jane (0s window)
```
O sea: con 5 frames posibles en la ventana, sobrevive **1**, y el span que se le pasa a la voz es
**0 segundos**. En el log de las 16:11 lo mismo (`frames=1/5`). El prompt que recibe la voz queda
`[look-at auto 0s]: ...` — le estamos diciendo que miró 0 segundos.

## Causa a confirmar (leé el código antes de tocar)
En `kateto/plugins/executor/static_vision_plugin.py`:
- `section_span(kept)` devuelve `0.0` cuando `len(kept) <= 1` (regla "un solo frame no tiene span").
- el span que se emite (`window_start`, `window_end`, y el del prompt de narración) sale de
  `min/max` de los timestamps de los frames **kept**, no de la ventana pedida.
- el `1/5` sugiere que los frames repetidos se descartan (dedupe por hash) — con una pantalla
  estática (el usuario estudiando un PDF) los 5 frames son iguales y queda 1.
Resultado: una escena quieta ⇒ span 0 ⇒ el prompt miente sobre la duración de la mirada.

## Fix esperado
1. El span que se reporta y el que va en el prompt (`[look-at <source> <span>s]`) tiene que ser la
   **duración real de la ventana** (la pedida, `window_secs`, y/o el tiempo transcurrido entre el
   primer y el último frame capturado **incluyendo** los descartados), nunca el span de los frames
   que sobrevivieron.
2. Si sólo hay un frame, informar la ventana igual y decir cuántos frames hay:
   p.ej. `[look-at auto 5s, 1 frame]`. Nada de "0s" cuando la ventana fue de 5.
3. No cambiar el dedupe (deduplicar está bien): lo que está mal es cómo se calcula el span.
4. Verificá también que `window_start`/`window_end` del evento `vision_describe_result` sean
   coherentes con eso (hoy salen de los kept).
5. **Un error del sidecar no es una descripción.** Hoy, cuando `describe_images` del sidecar falla,
   lo que vuelve es un texto de error y el plugin lo trata como descripción y lo narra: el usuario
   escuchó a la voz decir *"Uh, qué fallo más raro. La cámara se durmió o la red se fue de viaje."*
   (log: `sidecar describe_images answered (48 chars)` +
   `describe ... via=sidecar frames=1/5 chars=80` + `periodic narration -> jane`). Hay que:
   - detectar el caso error (el `isError` del resultado MCP y/o el texto de error del sidecar, que
     ya viene con la forma `video-rag describe_images: VLM unreachable at ... (model ...)` —
     ver `src/mcp.rs` del sidecar) y **no** emitir el `generate` de narración con eso;
   - loguear el motivo **completo** una vez (endpoint y modelo incluidos) para que sea diagnosticable
     sin adivinar;
   - que el look-at pedido por el usuario pueda decir que no pudo ver (eso es una respuesta), pero la
     narración ambiental no puede inventar ni repetir un error como si fuera lo que vio.

## Tests (obligatorios)
- Ventana estática: todos los frames idénticos ⇒ **un solo kept**, `span == window_secs` (> 0) y el
  prompt de narración contiene un span no-cero y la aclaración de frames.
- Ventana con movimiento: varios kept ⇒ span ≈ duración real.
- Un solo frame en la deque ⇒ span = ventana pedida (no 0).
- Los tests existentes de visión siguen verdes.

## Docs
- Bug nuevo (id siguiente) "describe de visión reporta ventanas de 0 s cuando la escena está quieta".
- `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **487 passed / 3 failed** preexistentes
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Cambiar la semántica del dedupe.
