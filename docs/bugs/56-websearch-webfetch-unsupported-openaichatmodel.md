---
id: 56
title: "WebSearch and WebFetch capabilities fail with OpenAIChatModel"
severity: Alta
status: resolved
resolved: 2026-08-09
component: kateto/voices/factory.py
---

## 56. WebSearch and WebFetch capabilities fail with OpenAIChatModel

**Severidad:** Alta
**Componente:** `kateto/voices/factory.py`

### Descripción

`_capabilities_for()` unconditionally appends `WebSearch()` and `WebFetch()` from `pydantic_ai.capabilities`. When `pydantic_ai` executes an agent using `OpenAIChatModel` (the standard provider model for OpenAI-compatible endpoints such as llama.cpp, vLLM, Ollama, DeepSeek), `pydantic_ai` raises a `UserError: WebSearchTool is not supported with OpenAIChatModel` and `Native tool(s) ['WebFetchTool'] not supported by this model`.

### Impacto

Voice speech generation (`speak` / `generate`) fails with a `UserError` on any setup using `OpenAIChatModel`.

### Causa

`WebSearch` and `WebFetch` are native capabilities requiring `OpenAIResponsesModel` or specific native model tool support. `OpenAIChatModel` does not support these native tools without local fallbacks.

**Solución aplicada:**
Removed `capabilities.append(WebSearch())` and `capabilities.append(WebFetch())` from `_capabilities_for()` in `kateto/voices/factory.py`.

**Archivos:** `kateto/voices/factory.py`
