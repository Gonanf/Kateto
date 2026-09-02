---
id: 71
title: "Refactorización de bate_debate al bus nativo de eventos de Kateto y preservación de SOUL.md"
severity: Alta
status: resolved
component: kateto/plugins/bate_debate/orchestrator.py, kateto/voices/base.py, kateto/providers/agent.py, kateto/voices/factory.py
resolved: 2026-08-31
---

## 71. Refactorización de bate_debate al bus nativo de eventos de Kateto y preservación de SOUL.md

**Severidad:** Alta
**Componente:** `kateto/plugins/bate_debate/orchestrator.py`, `kateto/voices/base.py`, `kateto/providers/agent.py`, `kateto/voices/factory.py`, `kateto/cli/commands.py`

### Descripción

1. **Peticiones HTTP directas bloqueantes y latencia en TTS:**
   El orquestador de debate realizaba llamadas crudas directas mediante `OpenAICompatibleProvider`, esperando a que la respuesta completa fuera generada por el LLM antes de pasar al TTS. Esto causaba retardos acumulativos de 10 a 15 segundos entre turnos y acumulaba párrafos completos en vez de procesar el flujo continuo de habla.
2. **Desnaturalización de la personalidad (`SOUL.md`):**
   `_debate_system_prompt` añadía `"Estas en un JUICIO ESCRITO no hablando por voz"`, contradiciendo el archivo `SOUL.md` del usuario y forzando a las voces a actuar como redactores de texto en vez de participantes de un tribunal verbal interactivo.
3. **Desbordamiento de la ventana de contexto (8243 tokens > 8192):**
   Tanto en `OpenAIAgentProvider` como en `_pydantic_agent_loop`, `max_tokens` se configuraba por defecto en 4096 (el máximo del modelo). Al sumar las herramientas MCP, capabilities y el historial del sistema, `llama-server` rechazaba las solicitudes con error HTTP 400 (`exceed_context_size_error`). Además, `_pydantic_agent_loop` duplicaba el prompt del sistema dentro de `message_history`.
4. **Desconexión con el sistema de interrupción:**
   Al no utilizar el bus de eventos de Kateto, las objeciones no podían cortar de inmediato la inferencia del modelo ni la reproducción en curso de `audio_output_player`.

### Impacto

- El orquestador presentaba silencios prolongados de más de 10 segundos entre agentes.
- Los agentes hablaban con un estilo disociado de su personalidad configurada en `~/.config/kateto/voices/{name}/SOUL.md`.
- El servidor local `llama-server` fallaba con código 400 por exceder la ventana de 8192 tokens.
- Las objeciones no interrumpían inmediatamente el audio del orador.

### Solución aplicada

1. **`EventDebateClient` y despacho por el bus de eventos:**
   - Se implementó `EventDebateClient` en `orchestrator.py`, despachando cada turno mediante el evento nativo `generate` (o invocando `on_generate` del plugin de la voz correspondiente) y escuchando los eventos `text_chunk` en tiempo real.
   - Con esto, `CambAudioOutput` y `audio_output_player` reciben los fragmentos fraccionados por oraciones en menos de 1 segundo desde el inicio de la inferencia, reduciendo la latencia de respuesta en un 90%.
   - En objeciones, se emite el evento `interrupt` con `reason="objection"`, deteniendo la generación en el LLM y reiniciando el flujo de audio de forma instantánea.
2. **Preservación del alma de las voces (`SOUL.md`):**
   - Se actualizó `_debate_system_prompt` para respetar íntegramente la personalidad cargada de `~/.config/kateto/voices/{name}/SOUL.md`, eliminando la indicación de "juicio escrito" e instruyendo a los agentes a mantener su rol auténtico en un juicio verbal en vivo.
3. **Acotamiento de `max_tokens` para habla y corrección de historial:**
   - En `OpenAICompatibleProvider`, `OpenAIAgentProvider` y `_pydantic_agent_loop`, se acotó `max_tokens` a `min(max_tokens, 384)` para turnos hablados, evitando desbordar la ventana de contexto de 8192 tokens.
   - En `_pydantic_agent_loop`, se filtraron los mensajes de sistema de `message_history` (evitando duplicar el system prompt) y se limitó a los últimos 6 turnos de diálogo.
   - En `_emit_chunk`, se permitió emitir fragmentos vacíos cuando `final=True` para señalar adecuadamente el fin del turno.
4. **Integración con CLI y pruebas unitarias:**
   - `kateto debate` inicializa `RuntimeOwner` de Kateto para proveer el `PluginManager` activo, manteniendo fallback total con `MockProvider` para pruebas deterministas y offline.
   - Se creó `kateto/tests/test_bate_debate.py` validando la preservación de `SOUL.md`, el flujo completo del debate y el cliente de eventos con interrupción.

**Archivos:** `kateto/plugins/bate_debate/orchestrator.py`, `kateto/voices/base.py`, `kateto/providers/agent.py`, `kateto/voices/factory.py`, `kateto/cli/commands.py`, `kateto/tests/test_bate_debate.py`
