---
title: "Doktor falla en generate — 'dict' object has no attribute 'conversation_id"
description: "38. Doktor falla en generate — 'dict' object has no attribute 'conversation_id'"
---


## 38. Doktor falla en generate — 'dict' object has no attribute 'conversation_id'

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`

### Descripción

Al disparar `generate`/`speak`, la voz (Doktor/Jane/Conquest) emite:

```
{"plugin":"doktor","event_name":"generate","error_type":"AttributeError","message":"'dict' object has no attribute 'conversation_id'"}
```

El traceback completo (capturado) apunta a:

```
base.py _pydantic_agent_loop
    result = await agent.run(user_prompt, message_history=history or None)
pydantic_ai/agent/__init__.py iter
    conversation_id=_agent_graph.resolve_conversation_id(conversation_id, message_history)
pydantic_ai/_agent_graph.py resolve_conversation_id
    if (cid := message.conversation_id) is not None:
AttributeError: 'dict' object has no attribute 'conversation_id'
```

### Impacto

Toda voz con el pydantic-ai Agent activo (cualquier `plugin.voice_llm.model`
configurado) crashea en el primer `generate` con historial no vacío. El bus
sobrevive (error aislado por plugin), pero la voz nunca responde.

### Causa

`_pydantic_agent_loop` construía `message_history` como lista de dicts
OpenAI-style (`{"role": ..., "content": ...}`). pydantic-ai exige objetos
`Message` reales (llevan `.conversation_id`); al iterar los dicts crudos,
`resolve_conversation_id` explota con AttributeError — antes de llegar a
cualquier servidor.

La hipótesis original (dict crudo re-hidratado desde el bus) era incorrecta:
el manager ya entrega la instancia del contrato. El `conversation_id` del
mensaje es un campo interno de pydantic-ai, no un parámetro del endpoint.

**Solución aplicada:**
1. Nuevo helper `_to_pydantic_messages()` en `kateto/voices/base.py` que
   convierte `ChatMessage` → `ModelRequest`/`ModelResponse` (con
   `SystemPromptPart`/`UserPromptPart`/`TextPart` según rol).
2. `_pydantic_agent_loop` usa ese helper para `message_history` en lugar de
   dicts crudos.
3. `pydantic_ai.messages` se importa a nivel de módulo (pydantic-ai es
   dependencia dura en `pyproject.toml`).

Nota: si un endpoint (p. ej. un harness tipo Hermes) exige `conversation_id`
en el cuerpo de la request, eso es un contrato distinto del proveedor y se
resuelve con un provider custom — no con este bug.

### Verificación

- Repro directo (`generate` → `voice_manager` → `speak` contra llama.cpp
  KatetoTalker) ya no emite error.
- `uv run pytest` → 157 passed.

**Archivos:** `kateto/voices/base.py`
