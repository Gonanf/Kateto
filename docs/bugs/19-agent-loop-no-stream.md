---
id: 19
title: "_agent_loop no hace streaming aunque stream=true en config"
severity: Alta
status: resolved
component: kateto/voices/base.py / kateto/providers/agent.py / kateto/voices/factory.py
resolved: 2026-07-19
---

## 19. `_agent_loop` no hace streaming aunque `stream=true` en config

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`, `kateto/providers/agent.py`, `kateto/voices/factory.py`

### Descripción

Cuando `plugin.voice_llm.model` está configurado (siempre es el caso), `factory.py` crea un `OpenAIAgentProvider` y lo asigna vía `voice.setup_agent()`. Esto hace que `_stream_response()` en `base.py` tome la ruta de `_agent_loop()` en lugar de la ruta de streaming directo con `OpenAICompatibleProvider.stream()`.

El problema: `_agent_loop` llamaba a `OpenAIAgentProvider.chat_with_tools()` que usaba `stream=False` en la API de OpenAI. La respuesta completa llegaba de una vez y se emitía como un único `text_chunk`.

La ruta de streaming real (en `_stream_response` lines 329-345) emitía tokens uno por uno, pero nunca se alcanzaba porque `_agent_provider` siempre está seteado.

### Impacto

- Toda respuesta de voz llegaba como un solo `text_chunk`, sin importar el valor de `stream` en config.
- El audio output (Zonos) no podía comenzar a reproducir hasta recibir el mensaje completo.
- Latencia percibida alta: silencio hasta que el LLM termina de generar toda la respuesta.

### Causa

`factory.py:48`: `if voice_settings.model:` → crea agente → `setup_agent()`.

`base.py:320`: `if self._agent_provider is not None and self._tool_executor is not None:` → siempre True si hay modelo configurado.

`agent.py:51`: `await self._client.chat.completions.create(**kwargs)` sin `stream=True`.

### Solución aplicada

1. **`agent.py`**: Agregado `StreamToken` y método `chat_with_tools_stream()` que usa `stream=True` en la API. Si el modelo responde con tool_calls, acumula los deltas y retorna un `AgentResponse` al final. Si responde con texto, yield `StreamToken` por cada delta.

2. **`base.py`**: Modificado `_agent_loop` para usar `chat_with_tools_stream()` cuando `self._settings.stream` es True. Los tokens se emiten uno por uno con `_emit_chunk(token, seq, final=False)`. El manejo de tool_calls se extrajo a `_handle_tool_calls()` para no duplicar lógica entre los caminos streaming y no-streaming.

**Archivos modificados:** `kateto/providers/agent.py`, `kateto/voices/base.py`
