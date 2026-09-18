---
id: 114
title: "El path pydantic ignora el SOUL: las voces suenan a asistente genérico"
severity: Alta
status: resolved
component: kateto/voices/factory.py
resolved: 2026-09-18
---

## 114. El path pydantic ignora el SOUL: las voces suenan a asistente genérico

**Severidad:** Alta
**Componente:** `kateto/voices/factory.py`, `kateto/voices/base.py`

### Descripción

En vivo: "los agentes hablan como si fueran asistentes y no personas con las
personalidades del SOUL.md". Editar el SOUL no cambiaba nada en el runtime.

### Impacto

La personalidad que ve el modelo era un párrafo genérico en inglés (el
arquetipo hardcodeado de `factory.py`), sin SOUL del usuario, sin regla de
idioma, sin skills ni memoria durable. Todo lo que el usuario escribe en
`SOUL.md` se ignoraba en el camino de generación que corre de verdad.

### Causa

El camino real es pydantic-ai: `base.py::_stream_response` (~854) → si hay
`_agent_provider` y `_tool_executor` → `_agent_loop` (~930) →
`if self._pydantic_agent is not None:` → `_pydantic_agent_loop` (~1039).

`_pydantic_agent_loop` arma los mensajes con `_messages_for(...)` (que SÍ
contiene el prompt estable con el SOUL) pero los tira:

```python
# For pydantic_agent message_history, skip system messages (agent already has its system prompt)
dialogue_messages = tuple(m for m in messages[:-1] if m.role in ("assistant", "user"))[-6:]
```

Y ese "system prompt" del agente era, en `factory.py` (~398):

```python
pydantic_agent = Agent(model=model, system_prompt=profile.system_prompt, ...)
```

o sea sólo `VoiceProfile.system_prompt` pelado. `VoiceAgent._stable_prompt()`
(~1231) ya hacía lo correcto (lee el SOUL con `read_soul()`, arma
`stable_prompt(soul=..., profile_system_prompt=..., response_language=..., ...)`
y lo congela por spawn): el bug era sólo que el agente pydantic no usaba ese
texto.

### Solución aplicada

- Nuevo método público `VoiceAgent.build_stable_prompt()` con la lógica de
  congelado; `_stable_prompt()` ahora delega en él.
- Al congelar, `VoiceAgent._sync_pydantic_system_prompt()` reemplaza
  `agent._system_prompts` por el texto congelado (pydantic-ai lo resuelve por
  run en `system_prompt_parts`, así que el prefijo queda estable toda la
  sesión). `set_pydantic_agent()` también sincroniza si el texto ya estaba
  congelado (attach tardío).
- `_pydantic_agent_loop` sigue salteando los system messages del historial
  (sin cambios): el texto estable vive SÓLO en el agente, no se duplica.
- Path no-pydantic intacto: ya usaba `_messages_for` con el prompt estable.
- Carrera de inicialización: el `Agent` no puede construirse con el texto
  estable en `factory.py` porque ese texto necesita `initialize()`
  (`memory.ensure_soul`, skills cargadas, tool executor para el bloque MCP y
  el propio agente para el bloque de delegación). `factory.py` lo deja
  asentado en un comentario: el seed es `profile.system_prompt` y el sync
  ocurre en `initialize()` vía `build_stable_prompt()`.
- Tests en `kateto/tests/test_pydantic_soul_prompt.py`: SOUL custom llega al
  agente (más arquetipo y regla de idioma), paridad byte a byte con el system
  message del path no-pydantic, SOUL duplicado no se duplica, SOUL escrito a
  mitad de sesión no cambia el congelado, attach tardío sincroniza.
- Corregida `docs/.../guides/como-usar.md`: el SOUL se lee al spawnear la voz
  dentro del prompt estable congelado (aplica al próximo spawn, nunca en
  caliente), no "como system_prompt al crear la voz".

**Archivos:** `kateto/voices/base.py`, `kateto/voices/factory.py`, `kateto/tests/test_pydantic_soul_prompt.py`, `docs/src/content/docs/guides/como-usar.md`
