---
title: "request_generation no se ejecuta con modelos que emiten tool calls como texto"
description: "Síntoma"
---


## Síntoma
Jane (o cualquier voz con el tool `request_generation`) "dice" que llama al tool
pero la otra voz nunca genera. En el log no aparecen `tool_call` / `generate_request`.

## Causa raíz
`VoiceAgent._stream_response` / `_agent_loop` (`voices/base.py`) esperan
`tool_calls` estructurados del provider (OpenAI-style `function_call`). El modelo
local `KatetoTalker` (1-bit) emite el tool call como **texto** dentro del contenido:
`<tool_call> {"name":"request_generation",...} </tool_call>`.

`base.py:_handle_tool_calls` solo se invoca cuando `provider.chat_with_tools_stream`
devuelve `AgentResponse(tool_calls=...)`. Como el modelo no devuelve tool_calls
estructurados, `_handle_tool_calls` nunca corre → la generación inter-voz no se
dispara.

## Impacto
La orquestación nativa (una voz consulta a otras vía `request_generation`) está
ROTA con modelos que no emiten tool_calls nativos. Esto afecta directamente el rol
de Jane como "juez" que debe recabar opiniones del panel.

## Workaround usado en la sesión
Orquestar desde fuera: enviar eventos `generate` individuales a cada voz vía
`POST /events/send`, y pasar las opiniones recabadas en el prompt de Jane.

## Fix sugerido
Parsear tool calls desde el texto del modelo (detector de `<tool_call>` / JSON) en
`_agent_loop` cuando el provider no devuelve tool_calls estructurados, o exigir un
modelo con tool-calling nativo (p.ej. Qwen) para voces que orquestan.
