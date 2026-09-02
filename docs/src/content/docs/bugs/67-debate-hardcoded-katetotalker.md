---
id: 67
title: "Comando debate ignora configuración de voice_llm por type-check y hardcodea modelo KatetoTalker"
severity: Alta
status: resolved
component: kateto/cli/commands.py
resolved: 2026-08-29
---

## 67. Comando debate ignora configuración de voice_llm por type-check y hardcodea modelo KatetoTalker

**Severidad:** Alta
**Componente:** `kateto/cli/commands.py`

### Descripción

Al ejecutar `uv run kateto debate`, la llamada al endpoint LLM fallaba con error HTTP 400:
`HTTP/1.1 400 Bad Request - {'error': {'code': 400, 'message': "model 'KatetoTalker' not found", 'type': 'invalid_request_error'}}`
a pesar de que el usuario tiene únicamente el modelo `Kateto` disponible y configurado en `[plugin.voice_llm] model = "Kateto"`.

### Impacto

El comando `debate` no podía ejecutarse con la configuración de usuario estándar, intentando contactar un modelo inexistente (`KatetoTalker`) y abortando el debate en la fase de apertura.

### Causa

En `kateto/cli/commands.py`, la función `_real_provider_factory()` realizaba:
1. Una inicialización por defecto de `model = os.environ.get("KATETO_LLM_MODEL", "KatetoTalker")`.
2. Una verificación `if isinstance(vllm, dict):` sobre `vllm = loaded.settings.plugin.get("voice_llm")`. Dado que `loaded.settings.plugin` almacena instancias de `PluginSettings` y no diccionarios planos, la condición evaluaba siempre a `False`. Por ende, los valores configurados por el usuario (`model`, `endpoint`, `api_key`) nunca eran extraídos del config y el modelo permanecía fijado en el fallback `"KatetoTalker"`.

**Solución aplicada:**

1. Se cambió el valor por defecto de modelo a `"Kateto"`.
2. Se actualizó la extracción de parámetros de `vllm` para soportar tanto instancias con atributos (como `PluginSettings`) mediante `getattr(vllm, ...)` como diccionarios mediante `.get(...)`.
3. Se garantizó la precedencia: variables de entorno (`KATETO_LLM_MODEL`, etc.) > archivo de configuración (`voice_llm`) > valores por defecto (`"Kateto"`, `"http://localhost:11434/v1"`).
4. Se actualizó `gen_discussion.py` para seguir la misma resolución dinámica.
5. Se añadieron tests unitarios en `kateto/tests/test_cli_live.py`.

**Archivos:** `kateto/cli/commands.py`, `gen_discussion.py`, `kateto/tests/test_cli_live.py`
