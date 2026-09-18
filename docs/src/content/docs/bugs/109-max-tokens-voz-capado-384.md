---
id: 109
title: "`max_tokens` de la voz capado silenciosamente a 384"
severity: Media
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-18
---

## 109. `max_tokens` de la voz capado silenciosamente a 384

**Severidad:** Media
**Componente:** `kateto/voices/base.py`

### Descripción

`OpenAICompatibleProvider._stream` mandaba
`max_tokens=min(self.max_tokens or 256, 384)`, así que el `max_tokens = 4096`
configurado por voz llegaba al proveedor como **384** sin ningún aviso en el log.
El mismo cap reaparecía en `_pydantic_agent_loop`
(`ModelSettings(max_tokens=min(...))`), en `factory.py` y en
`OpenAIAgentProvider._base_kwargs` (`kateto/providers/agent.py`).

### Impacto

Respuestas de voz truncadas aunque el usuario configurara un límite alto;
el valor de config no era el que iba en el cable y no había forma de notarlo
sin inspeccionar el payload.

### Causa

Cap local heredado del refactor del debate (bug 71), donde se acotó a 384
para no desbordar la ventana de 8192 tokens con tools+MCP+historial. Quedó
aplicado también al path HTTP directo de `voice_llm`, donde el gateway ya
clampea por proveedor ("Effective max_tokens is min(requested, provider ceiling)").

### Solución aplicada

- Los cuatro paths usan el valor configurado tal cual; default 256 sólo
  cuando no está seteado. Sin cap local.
- Tests en `kateto/tests/test_voice_llm_params.py`: 4096 llega verbatim,
  sin configurar → 256, y el path con tools sigue construyendo requests.

**Archivos:** `kateto/voices/base.py`, `kateto/voices/factory.py`, `kateto/providers/agent.py`, `kateto/tests/test_voice_llm_params.py`
