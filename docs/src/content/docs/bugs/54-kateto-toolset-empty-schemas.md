---
title: "KatetoToolset envía herramientas con esquemas de parámetros vacíos"
description: "54. KatetoToolset envía herramientas con esquemas de parámetros vacíos"
---


## 54. KatetoToolset envía herramientas con esquemas de parámetros vacíos

**Severidad:** Alta
**Componente:** `kateto/voices/tools.py`

### Descripción

En el path por defecto de voz (no-hermes, vía pydantic-ai `Agent`), las herramientas llegan al modelo con un esquema de parámetros **vacío**: `{"type": "object", "properties": {}}` para todas ellas. Un modelo que recibe `write_file` sin propiedades `path`/`content` no puede construir la llamada y responde con texto en lugar de ejecutar la herramienta. Síntoma observado: al pedir "genera un archivo markdown" con deepseek v4-flash, el modelo no llamó ninguna tool.

### Impacto

Ninguna herramienta es usable en el path pydantic-ai (el default para cualquier endpoint OpenAI-compatible sin `conversation_id`): ni `write_file`, ni `read_file`, ni `run_command`, ni las de eventos. El agente responde prosa pero no produce artefactos.

### Causa

`KatetoToolset._build_toolset()` calculaba `parameters = tool_def["function"]["parameters"]` pero **nunca lo pasaba** a `ts.add_function(...)`. `add_function` no acepta un esquema: infiere el esquema del *signature* de la función envuelta, que es `async def _tool(**kwargs: Any)` — un `**kwargs` sin anotaciones produce un esquema objeto sin propiedades.

### Solución aplicada

Se inyecta el esquema real en tiempo de request mediante el hook `prepare` de pydantic-ai, que recibe el `ToolDefinition` y permite reemplazar `parameters_json_schema`:

```python
def _make_prepare(self, tool_name: str, parameters: dict[str, Any]) -> Any:
    del tool_name
    def _prepare(ctx: Any, tool_def: Any) -> Any:
        del ctx
        tool_def.parameters_json_schema = parameters
        return tool_def
    return _prepare
```

Además:
- Se agregó la herramienta `delete_file` (ejecutor + esquema) para completar el ciclo de archivos.
- Descripciones de `read_file`, `write_file` y `delete_file` más descriptivas (rutas relativas, uso de deliverable).

Regresión cubierta por `kateto/tests/test_kateto_toolset.py`: verifica que cada `BUILTIN_TOOL` declara propiedades y que el `prepare` inyecta exactamente el esquema esperado.

**Archivos:** `kateto/voices/tools.py`, `kateto/tests/test_kateto_toolset.py`
