# Las voces hablan como asistentes: el path pydantic descarta el SOUL del usuario

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, en vivo)
"Los agentes hablan como si fueran asistentes y no personas con las personalidades del SOUL.md."

## Causa (leída en el código; confirmala antes de tocar)
El camino de generación que corre de verdad es el de pydantic-ai:
`base.py::_stream_response` (línea ~854) → si hay `_agent_provider` y `_tool_executor` → `_agent_loop`
(~930) → **`if self._pydantic_agent is not None:` → `_pydantic_agent_loop`** (~1039).

`_pydantic_agent_loop` arma los mensajes con `self._messages_for(...)` (que SÍ contiene el prompt estable
con el SOUL) pero **los tira**:
```python
# For pydantic_agent message_history, skip system messages (agent already has its system prompt)
dialogue_messages = tuple(m for m in messages[:-1] if m.role in ("assistant", "user"))[-6:]
```
Y ese "system prompt" del agente es, en `factory.py` (~396):
```python
pydantic_agent = Agent(model=model, system_prompt=profile.system_prompt, ...)
```
o sea **sólo el arquetipo hardcodeado de `factory.py`** (`VoiceProfile.system_prompt`, un párrafo en
inglés del estilo "You are Jane. Personality archetype: absurd situational comedy..."), **sin** el
`SOUL.md` del usuario, sin la regla de idioma, sin las skills y sin la memoria durable que sí arma
`voices/context.py::stable_prompt()`.

Consecuencia exacta del síntoma: editar el SOUL no cambia nada en el runtime — la personalidad que ve el
modelo es un párrafo genérico, y eso suena a asistente.

Nota: `VoiceAgent._stable_prompt()` (~1231) ya hace lo correcto (lee SOUL con `read_soul()`, arma
`stable_prompt(soul=..., profile_system_prompt=..., response_language=..., ...)` y lo congela por spawn).
El bug es sólo que el agente pydantic no usa ese texto.

## Fix
- `factory.py`: construir el `Agent` con **el mismo prompt estable congelado** que usa la voz, no con
  `profile.system_prompt` pelado. Concretamente: exponer un método público en `VoiceAgent`
  (p.ej. `build_stable_prompt()`, y que `_stable_prompt()` lo use) y pasarlo como `system_prompt=` al
  `Agent(...)`. Si preferís lazy, `system_prompt` puede ser un callable que devuelva el texto ya congelado
  (`_stable_prompt_text`) — **no** una función que recalcule por request: el prefijo tiene que quedar
  estable durante la sesión (es el prefijo cacheable, ver comentario en `context.py`).
- Verificá que no se duplique el system prompt: `_pydantic_agent_loop` sigue salteando los system
  messages del historial (eso está bien, no lo cambies) y el texto va **sólo** en el agente.
- Ojo con el orden de construcción en `factory.py`: el agente pydantic se crea después de `voice` y antes
  de `set_pydantic_agent`. La memoria del voice (`_memory`) tiene que estar lista para `read_soul()`.
  Si hay una carrera de inicialización, resolvela explícitamente y explicá cómo.
- Dejá el path NO-pydantic (`_agent_loop` con `chat_with_tools_stream` y el provider HTTP) como está: ya
  usa `_messages_for` con el prompt estable.

## Tests (obligatorios)
- Con una config temporal (`tmp_path`) y un `SOUL.md` **custom**: el `system_prompt` del agente pydantic
  contiene el texto del SOUL (y el arquetipo del perfil, y la regla de idioma).
- **Paridad**: el `system_prompt` del agente pydantic es igual al que se manda como system message en el
  path no-pydantic para la misma voz (`_stable_prompt()`), así no pueden divergir otra vez.
- Un `SOUL.md` idéntico al prompt del perfil sigue sin duplicarse (comportamiento actual de `stable_prompt`).
- Un `SOUL.md` que se escribe a mitad de sesión **no** cambia el prompt ya congelado (sigue congelado).
- Los tests existentes de `test_prompt_context.py` / voces siguen verdes.

## Docs
- Bug nuevo (id siguiente) "el path pydantic ignora el SOUL: las voces suenan a asistente genérico",
  con el código citado y el efecto.
- `known-issues.md`.
- Si alguna doc afirma que el SOUL se aplica siempre, corregila.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "prompt or voice or soul"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **475 passed / 3 failed** preexistentes
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Reescribir `stable_prompt` para "mejorarlo"
  más allá de lo necesario: el objetivo es que el path pydantic use ESE texto.
