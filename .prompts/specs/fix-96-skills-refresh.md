# Bootstrap: refrescar las skills bundled que quedaron viejas en la config del usuario

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`
(HEAD `a907601`). Seguí ahí. **NO commitees**: dejá el diff visible.

## Causa (verificada en el runtime real del usuario, no hipótesis)
El bootstrap de skills copia **sólo los archivos que faltan** ("copy-missing, no pisa"), así que una skill
bundled que mejora en el repo queda vieja en la config del usuario **para siempre**.
Medido en su home: `~/.config/kateto/skills/look-at/SKILL.md` = **1322 bytes** contra **1918** del repo, y
lo que falta es exactamente la sección `## How to trigger a look` — la que le dice a la voz que la mirada se
pide con `send_event(event_name="vision_describe_request", data={"requester","source"})`.
Síntoma reportado: la voz contesta *"no tengo herramienta para ver las pantallas"*. El tool existe (se genera
un tool por evento registrado y `vision_describe_request` está registrado mientras el plugin de visión vive);
lo que no existe es la instrucción, porque su skill es vieja.
Las otras cuatro skills compartidas están idénticas al repo: el drift fue sólo en `look-at`.

## Fix
- En el backfill/bootstrap de skills bundled (buscá `ensure_shared_skill` y quien lo llama; arrancá por
  `kateto/plugins/executor/static_vision_plugin.py` y `kateto/core/config.py`), dejar de ser
  copy-missing-only: si el archivo del bundle **difiere** del de la config del usuario, refrescarlo
  guardando un backup `.bak.<timestamp>` al lado y loguear `[skills] refreshed <name> (bundled changed)`.
- Límites (no pisar trabajo del usuario):
  * Sólo para las skills que el código ya considera bundled/compartidas (las que hoy backfillea).
    **NO** tocar skills creadas por el usuario ni las que una voz escribe con `create_skill`/`update_skill`.
  * Nunca borrar el archivo viejo: backup con timestamp; si ese backup ya existe, no sobreescribirlo.
  * Si el archivo del usuario es idéntico: no tocar nada y no loguear.
- El `--force` del CLI `install` y el copy-missing de packs **no cambian de semántica**: esto es sólo el
  backfill automático de skills bundled.

## Tests (obligatorios)
- Skill bundled vieja en la config → se refresca, queda `.bak.<timestamp>` y se loguea.
- Skill bundled idéntica → no se toca, sin backup nuevo.
- Skill de usuario (no bundled, p.ej. creada por una voz) → intacta.
- Idempotencia: correr el bootstrap dos veces seguidas no genera backups extra ni cambia contenido.
- El resto de la suite, igual.

## Docs
- Bug nuevo con el **siguiente id libre** (verificá el máximo en `docs/src/content/docs/bugs/`):
  "las skills bundled no se refrescan: la copia del usuario queda vieja".
- `known-issues.md` actualizado.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "skill or config or vision"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline actual del worktree: **470 passed / 3 failed**
   preexistentes (`test_audio_capture::raw_int16` y 2 de `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Tocar la config del usuario (la de study es de sólo lectura para nosotros: acá se cambia el CÓDIGO que la
  refresca, no sus archivos) ni contratos de eventos.
- Subagentes/task. Commitear. Inventar verificación.
