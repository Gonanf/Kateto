---
id: 110
title: "`thinking=false` no llega al proveedor (no se manda reasoning_effort)"
severity: Media
status: resolved
component: kateto/providers/agent.py
resolved: 2026-09-18
---

## 110. `thinking=false` no llega al proveedor (no se manda reasoning_effort)

**Severidad:** Media
**Componente:** `kateto/providers/agent.py` (antes: `kateto/voices/base.py`)

### Descripción

`settings.thinking` sólo quitaba la capability `Thinking()` de pydantic-ai
(`factory.py`), que aplica al path del agente con tools. El path HTTP de
`voice_llm` (`OpenAICompatibleProvider._stream`) mandaba
`model/messages/stream/max_tokens/extra_headers` y nada de reasoning, así que
`thinking=false` nunca llegaba al proveedor y el modelo que elige el router
podía pensar igual (TTFT de 105 s en nemotron-3-ultra-550b vs 0.8 s en
gpt-oss-120b, medido en runtime contra FreeLLMAPI).

### Impacto

Sin forma de pedirle al gateway que apague el reasoning desde la config de la
voz; latencia de primer chunk dominada por el modelo elegido por el router.

### Causa

El knob `thinking` nunca se traducía a parámetro del cable en el path HTTP.
El gateway sí entiende `reasoning_effort` (`none|minimal|low|medium|high`,
más alias `off|disabled|disable` → `none`), lo normaliza y lo droppea por
proveedor cuando no aplica sin fallar el request.

### Solución aplicada

- Nuevo knob por voz `reasoning_effort` (retrocompatible, `extra="allow"`):
  seteado → va tal cual; no seteado + `thinking=false` → `"none"`;
  `thinking=true` → no se manda (decide el modelo).
- Se manda por `extra_body={"reasoning_effort": ...}` en
  `client.chat.completions.create(...)` (el SDK rechaza kwargs desconocidos).
- Log una vez por spawn a INFO:
  `[provider] reasoning_effort=... thinking=... model=...`.
- Knob documentado en `config/defaults/config.toml` (comentado) y en
  `docs/.../architecture/config.md`. Sin cambios en contratos de eventos ni
  en defaults de las otras voces.
- Tests en `kateto/tests/test_voice_llm_params.py` para las tres ramas de la regla.

**Archivos:** `kateto/voices/base.py`, `kateto/voices/factory.py`, `kateto/core/config.py`, `config/defaults/config.toml`, `kateto/tests/test_voice_llm_params.py`

### Addendum 2026-09-18: el camino real era el agent provider

El fix anterior cableó `reasoning_effort`/`thinking` en
`OpenAICompatibleProvider` (`kateto/voices/base.py`), pero las voces del
usuario no pasan por ahí: `factory.py` construye además un
`OpenAIAgentProvider` (o `HermesProvider` si hay `conversation_id`) y, como
`voice_llm.model` está seteado y la voz tiene tools/skills/MCP, la generación
la hace `kateto/providers/agent.py`. Ahí `_base_kwargs` sólo mandaba `model`,
`max_tokens`, `stream` y `extra_headers`: ningún parámetro de reasoning.

Evidencia del runtime (repo en `912931a` = con el fix anterior): request
`POST http://127.0.0.1:3001/v1/chat/completions "200 OK"` sin la línea
`[provider] reasoning_effort=...` (sólo se logueaba desde `base.py`, que en
este path nunca corre); primer chunk a los 5.25 s con
`nemotron-3.5-lightning-30b-a3b` contra 1.85 s con `reasoning_effort="none"`
en la misma máquina y mismo tipo de prompt.

Fix aplicado: `OpenAIAgentProvider.__init__` y `HermesProvider.__init__`
aceptan `reasoning_effort`/`thinking` y `_base_kwargs` mergea `extra_body`
con la misma regla importada de `base.py::resolve_reasoning_effort`
(explícito gana; `thinking=False` → `"none"`; `thinking=True` → no se manda;
si el effort es None no se agrega la clave ni un `extra_body` vacío).
`HermesProvider` mergea `{"conversation_id": ...}` con `reasoning_effort` en
vez de pisarlo. `factory.py` pasa `reasoning_effort`/`thinking` a ambos
providers. Log una vez por instancia con el mismo formato `[provider]
reasoning_effort={} thinking={} model={}`.

**Archivos (addendum):** `kateto/providers/agent.py`, `kateto/voices/factory.py`

### Addendum 2026-09-18 (2): el que corre es el agente pydantic

Ninguno de los dos caminos anteriores corre en el runtime del usuario: sus
voces van por el **agente de pydantic-ai** (`_pydantic_agent_loop`), que arma
su propio modelo (`OpenAIChatModel` + `OpenAIProvider`) y sus settings en
`kateto/voices/factory.py`. Ahí el `Agent` se construía con
`ModelSettings(max_tokens=...)` sin reasoning, así que `thinking=false`
tampoco llegaba al proveedor por este camino.

Evidencia del runtime: la línea `[provider] reasoning_effort=...` **nunca**
aparece en el log del usuario (sólo se logueaba desde los otros dos
providers, que en este path nunca corren); primer chunk a ~5 s con
`nemotron-3.5-lightning-30b-a3b` contra **1.85 s** con
`reasoning_effort="none"` en la misma máquina y prompt del mismo tamaño.
Todas las voces tienen `thinking = false`, así que la regla esperada es
mandar `"none"`.

Fix aplicado: `factory.py` calcula el esfuerzo con la misma
`kateto.voices.base::resolve_reasoning_effort` (importada, sin duplicar la
regla) y lo pasa por `extra_body` de `ModelSettings`
(`extra_body={"reasoning_effort": effort}` sólo si hay effort; con
`thinking=True` no se agrega la clave ni un `extra_body` vacío). Log una vez
al construir el agente con el mismo formato más sufijo `(pydantic)`:
`[provider] reasoning_effort={} thinking={} model={} (pydantic)`. No hizo
falta tocar `_pydantic_agent_loop`: su `m_settings` por-request mergea sobre
los settings del Agent (precedencia run > agent, `merge_model_settings` hace
`base | overrides`) sin la clave `extra_body`, así que el valor del Agent
sobrevive; y `OpenAIChatModel` manda `model_settings.get('extra_body')` al
request (verificado en el venv, pydantic-ai 2.26).

Quedan así **tres** caminos cableados con la misma regla: `OpenAICompatibleProvider`
(`base.py`), `OpenAIAgentProvider`/`HermesProvider` (`providers/agent.py`) y
el agente pydantic (`voices/factory.py`) — este último es el que corre.

**Archivos (addendum 2):** `kateto/voices/factory.py`, `kateto/tests/test_voice_llm_params.py`
