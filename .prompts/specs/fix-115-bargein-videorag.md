# Barge-in: el video-rag y la narración que pide no se interrumpen cuando el usuario habla

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## REGLA 0 (leela primero)
**Prohibido explorar.** No recorras el repo ni busques de más: los archivos y las líneas están abajo.
Abrí sólo eso y andá directo al patch. Los tests que tenés que escribir son los de la sección **Tests**.

Anclas:
- `kateto/plugins/executor/static_vision_plugin.py` — `register_event(...)` en `initialize()` (~línea
  426), `on_vision_describe_request` (~733), el emit de la narración (~979: `manager.emit("generate",
  GenerateData(prompt=f"[look-at ...]"))`), `self._periodic_retry_tasks` (~416).
- `kateto/core/event.py` — `GenerateData` (~177: sólo `prompt`, `workflow`, `phase_id`),
  `InterruptData` (~165: `reason`, `dept`).
- `kateto/plugins/system/turn_gate.py` — `on_interrupt` (~104) y `decide` (~140).
- `kateto/voices/base.py` — `on_interrupt` (~755), `on_generate` (~766), `_pass_turn_gate` (~889).
- Tests: `kateto/tests/test_vision_ocr_detect.py`, `kateto/tests/test_turn_gate*.py`,
  `kateto/tests/test_vision_random_interval.py`.

## Causa (leída en el código)
Cuando el usuario habla encima de la narración del video-rag:

1. El plugin de visión **no escucha `interrupt`** (no está en su `register_event`): el
   `describe_images` en vuelo sigue corriendo (hasta 120 s) y, cuando vuelve, **emite la narración
   igual**.
2. Esa narración entra como un `generate` sin marca de origen: `TurnGate.decide` la trata como
   `"external"` — la **misma prioridad que el turno del usuario**. Consecuencias exactas:
   - `self._barge_in.discard(voice)` **borra la marca de barge-in** del usuario,
   - si no hay turno activo ⇒ `EXECUTE` inmediato (habla encima/después del usuario),
   - si hay turno activo ⇒ `QUEUE` con `front=True` (se **adelanta** en la cola y habla apenas termina).
3. Además `on_generate` hace `self._interrupted = False` al arrancar, así que la narración **borra el
   estado de interrupción** del barge-in.

El audio sí se corta (player/TTS tienen `on_interrupt`) — lo que no se corta es el pedido al sidecar ni
la generación que ese pedido dispara. Es exactamente lo que reporta el usuario.

## Fix esperado

### 1. La narración ambiental es de otra prioridad (nunca le gana al usuario)
- Agregá un campo de origen a `GenerateData` (opcional, con default, para no romper los emisores
  existentes): valores `external` (usuario/sistema), `followup` (inter-voz) y **`ambient`** (narración
  del video-rag). `EventModel` es estricto: default explícito y compatible.
- `static_vision_plugin` emite la narración con `origin="ambient"`.
- `VoiceAgent.on_generate`: el origen sale de `data.origin` si viene, si no de la lógica actual
  (`_followup_pending` ⇒ followup, si no external). **Ojo:** `self._interrupted = False` no puede
  ejecutarse para `ambient` (no puede borrar el estado de un barge-in del usuario).
- `TurnGate.decide` con `origin="ambient"`:
  - **DISCARD** (nunca QUEUE, nunca EXECUTE) si el usuario interrumpió desde que se pidió la narración,
    o si hay un turno de usuario activo (`_active is not None`) o pendiente en `_pending`.
  - **Nunca** toca `_barge_in`, nunca reclama `_active`, nunca se encola (ni siquiera al frente).
  - Si no hay nadie hablando y el usuario no interrumpió: EXECUTE (como hoy).

### 2. El pedido al sidecar se cancela y los resultados viejos se tiran
- El plugin tiene que **suscribirse a `interrupt`** y, cuando `reason` sea de usuario
  (`voice_activity` / `user_turn`): cancelar la tarea de describe en vuelo de esa voz
  (`self._periodic_retry_tasks`), y subir una **época** (`self._user_epoch += 1` o equivalente).
- La narración captura la época **antes** de pedir el describe y, al volver, si la época cambió ⇒
  **descarta** el resultado (no emite `generate`, no narra) y deja log con el motivo. Así un describe
  que tardó 90 s no sale a hablar cuando el usuario ya habló.
- Lo mismo para el look-at pedido por el usuario: ahí el pedido es del usuario y **sí** se responde,
  pero si el usuario volvió a hablar encima, se descarta igual (su turno nuevo gana).
- Reprogramar el próximo tick (respetando el rango aleatorio de fix-112) después de un descarte.

### 3. No hables encima
Cualquier camino de la narración ambiental tiene que chequear que no haya un turno de usuario
THINKING/SPEAKING antes de emitir. Si lo hay, se descarta la narración (y se loguea). El timer sigue
corriendo: no se pierde el ciclo, se saltea.

## Tests (obligatorios)
- Plugin: con `interrupt` de usuario en medio del describe ⇒ la tarea en vuelo se cancela y **no** se
  emite `generate`; un resultado que vuelve con la época vieja se descarta con log.
- Gate: `origin="ambient"` ⇒ DISCARD con turno activo, DISCARD con `_pending` sin vaciar, DISCARD tras
  barge-in reciente; **nunca** borra `_barge_in`; **nunca** encola; EXECUTE sólo cuando el usuario no
  habló ni hay turno activo.
- Voz: `on_generate` con `origin="ambient"` **no** resetea `_interrupted`; con el resto sí (comportamiento
  actual intacto).
- Compatibilidad: los emisores que hoy no mandan origen siguen igual (usuario, followup, workflow).
- El look-at pedido por el usuario sigue respondiendo si no hay barge-in posterior.

## Verificación (sin `| tail`, reportá los conteos)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or turn_gate or interrupt or voice"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline actual: **565 passed / 3 failed**
   (los 3 fallan de antes: `test_audio_capture`, 2 de `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes. Cambiar la prioridad del turno del usuario. Que la narración se encole al
  frente. Romper los emisores de `generate` que hoy no mandan origen (classifier, workflow_router,
  bate_debate, http_server, openai_server, voice_manager).
