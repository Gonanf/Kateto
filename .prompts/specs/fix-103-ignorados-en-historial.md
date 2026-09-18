# Los mensajes que el clasificador ignora quedan en el historial sin marca y el LLM los contesta después

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"Los mensajes ignorados por el clasificador son respondidos constantemente por mensajes posteriores
de los LLM. Si yo digo 'Gracias.', entonces el LLM debería tener en el mensaje ese 'Gracias.' pero
también saber que no debe responderlo si lo ve como último mensaje de usuario. Tal vez colocarle como
un mensaje de sistema que diga 'ESTE MENSAJE FUE IGNORADO' o algo así."

## Causa (leída en el código; confirmala)
- `kateto/plugins/system/turn_gate.py`: `on_classification` guarda el texto ignorado en `_ignored`
  (deque maxlen 8) y `decide()` hace `if self._consume_ignored(prompt): return Decision.DISCARD`.
  Eso evita **disparar** un turno con ese texto, pero no toca el historial.
- `kateto/voices/base.py::VoiceAgent._enqueue` hace `self._remember_event(envelope)` para **todos**
  los eventos, incluido `transcription` (línea ~613): o sea la transcripción ignorada ("Gracias.")
  queda registrada en el historial de la voz como mensaje de usuario.
- Cuando llega un turno posterior por otra vía (narración de visión, follow-up, o un pedido real),
  el historial que se manda al modelo termina con ese `user: Gracias.` sin ninguna marca ⇒ el modelo
  lo contesta como si fuera el último pedido del usuario.

## Fix esperado
1. Cuando una transcripción se clasifica como ignorada (`IGNORE_SELF_TALK`, `IGNORE_THIRD_PARTY` y
   cualquier otra categoría de ignorado del enum `Classification`), el historial tiene que llevarla
   **con marca explícita** y el texto original visible. Ejemplo de la intención:
   `ESTE MENSAJE FUE IGNORADO POR EL CLASIFICADOR — NO LO RESPONDAS: "Gracias."`
2. **Ojo con el camino pydantic** (es el que corre en el runtime del usuario,
   `base.py::_pydantic_agent_loop`): ese loop filtra `m.role in ("assistant","user")`, así que un
   mensaje `system` intercalado **se descarta**. Si la marca va como mensaje aparte, extendé el
   filtro de forma explícita para que la marca sobreviva; si no, prefijá el **contenido** del mensaje
   de usuario (`[IGNORADO — no responder] Gracias.`), que es lo más robusto para los dos caminos.
   Elegí una y explicá por qué; que se vea en el prompt final.
3. La marca vive en el **historial por turno** (parte volátil), nunca en el prompt estable congelado
   (`voices/context.py::stable_prompt`): el prefijo cacheable no puede cambiar por esto.
4. Nada de duplicar el texto ni de perder el descarte actual: si el texto vuelve a llegar solo, el
   turno se sigue descartando (`_consume_ignored`).
5. Que funcione para las voces con y sin tools/agente.

## Tests (obligatorios)
- Una transcripción clasificada como ignorada ⇒ el historial la contiene **con** la marca y el texto.
- El siguiente turno, armado con `_messages_for`/`build_stable_prompt`, incluye la marca en la parte
  volátil y **no** la incluye en el prompt estable.
- Camino pydantic: la marca sobrevive al filtro de `_pydantic_agent_loop` (test con el mismo patrón de
  fakes que ya usa la suite).
- Regresión: el texto ignorado que llega como prompt sigue devolviendo `Decision.DISCARD`.
- Los tests existentes de `turn_gate`/clasificador/voces siguen verdes.

## Docs
- Bug nuevo (id siguiente) "mensajes ignorados por el clasificador: quedan sin marca y el LLM los
  contesta en el turno siguiente".
- `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "gate or classifier or history or prompt"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **487 passed / 3 failed** preexistentes
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Inventar que el modelo "ya lo entiende":
  la marca tiene que estar en el texto que se manda.
