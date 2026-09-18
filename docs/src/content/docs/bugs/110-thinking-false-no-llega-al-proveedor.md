---
id: 110
title: "`thinking=false` no llega al proveedor (no se manda reasoning_effort)"
severity: Media
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-18
---

## 110. `thinking=false` no llega al proveedor (no se manda reasoning_effort)

**Severidad:** Media
**Componente:** `kateto/voices/base.py`

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
