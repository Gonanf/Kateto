# Visión: no narrar sin descripción real, revolver la precedencia de config por voz y exponer el motivo del sidecar

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Contexto medido (runtime real del usuario, hoy)
1) La voz se puso a hablar **sola** cada 30 s. En el log:
```
[vision] periodic describe opted in: jane@30s
[scheduler] job vision-describe-jane fired -> vision_describe_request
[vision] sidecar video_rag unreachable (no client or no describe_images tool)
[vision] describe requester=scheduler:jane source=auto via=recap frames=1/5 chars=157
[vision] periodic narration -> jane (0s window)          <- y la voz HABLA
```
2) La causa de fondo del punto 1 (y del look-at roto) es la **precedencia de config por voz**:
`kateto/core/config.py::_load_voice_folder_configs` (línea ~337) hace
```python
existing = voices_section.get(vname, {})
voices_section[vname] = {**existing, **vsettings}     # voices/<voz>/config.toml PISA a [voice] <voz>.*
```
y en el home del usuario `voices/jane/config.toml` tenía `vision_periodic = true`,
`skills = ["orchestrator"]` y `mcp_servers = ["system"]`, mientras el `config.toml` principal decía
`jane.vision_periodic = false`, `jane.skills = ["orchestrator","look-at"]` y
`jane.mcp_servers = ["system","video_rag"]`. Gana el archivo por voz **en silencio**: por eso la narración
ambiental seguía prendida, la voz no tenía la skill `look-at` y el cliente MCP `video_rag` no existía
(de ahí el "sidecar unreachable"). El usuario ya lo está arreglando en su config; lo que falta es el código.

## Fix, tres partes

### A. Que la precedencia deje de ser silenciosa (el footgun)
- En `_load_voice_folder_configs`, cuando una clave venga **también** en el `[voice]` del config principal
  y el archivo por voz la pise, dejar registro explícito: nombre de la clave, valor del principal, valor
  del archivo por voz y el archivo que ganó. Una línea por clave y por voz, al cargar. Usá el logger del
  módulo si existe (o `warnings.warn` / el mecanismo que ya use `config.py`); tiene que verse en un arranque
  normal con `log_level = INFO`.
- `kateto config check` (o el doctor) debe poder mostrar los **valores efectivos por voz** y de dónde sale
  cada clave cuando hay conflicto. Si ya hay un comando parecido, extendelo; no inventes otro.
- Documentaló donde corresponde (guía de configuración): el archivo por voz tiene prioridad sobre
  `[voice] <voz>.*` del config principal.

### B. No narrar cuando no hay descripción real
- Si el describe cayó al **recap** (sin endpoint VLM y sin sidecar), el camino periódico **no** debe emitir
  el `generate` de narración: hoy hace hablar a la voz con un texto que no describe nada ("la visión no está
  configurada"). Silencio en ese caso, y un warning una vez (no cada 30 s).
- Una descripción pedida **por el usuario** sí puede contestar que no pudo ver (eso es una respuesta a una
  pregunta); lo que no puede pasar es narrar solo porque el recap existe.
- Si el describe real llegó (via=vlm o via=sidecar), la narración periódica sigue como está.

### C. Exponer el motivo real del "sidecar unreachable"
- `static_vision_plugin._describe_fallback` loguea un mensaje que mezcla dos causas ("no client or no
  describe_images tool"). Separá las dos: sin cliente MCP configurado / con cliente pero sin la tool en la
  sesión, e incluí el motivo real si `ExternalMcpManager` lo tiene (arranque fallido, handshake, timeout,
  binario inexistente). Hoy ese motivo se pierde y nos costó una tarde de diagnóstico.

## Tests (obligatorios)
- Precedencia: un `voices/<voz>/config.toml` que pisa una clave del principal → se registra el aviso con
  los dos valores y el archivo ganador; el valor efectivo sigue siendo el del archivo por voz (no cambies
  la semántica, sólo hacela visible).
- Recap → **no** se emite narración periódica y se avisa una vez. Describe real → sí se emite.
- Los dos motivos distintos del fallback se distinguen en el log.
- Los tests existentes de vision/config siguen verdes.

## Docs
- Bug nuevo (id siguiente, verificá el máximo en `docs/src/content/docs/bugs/`) con la cadena completa:
  config por voz pisa al principal → narración periódica activa → sidecar sin cliente → recap → la voz habla.
- `known-issues.md` y la guía de configuración.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or config"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **487 passed / 3 failed** preexistentes
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario (su archivo por voz lo arregla él con un script
  aparte; acá se cambia el CÓDIGO). Cambiar la semántica de la precedencia sin pedirlo.
