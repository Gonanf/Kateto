---
id: 134
title: "`kateto run` muere con 'PluginSettings' object has no attribute 'token'"
severity: Alta
status: resolved
component: kateto/plugins/system/__init__.py
resolved: 2026-11-08
---

## 134. `kateto run` muere con 'PluginSettings' object has no attribute 'token'

**Severidad:** Alta
**Componente:** `kateto/plugins/system/__init__.py:71`

### Descripción

`uv run kateto run` abortaba al ensamblar los plugins del sistema, justo después de
`HttpServer enabled in config. Instantiating on 127.0.0.1:8099`, con el mensaje
`'PluginSettings' object has no attribute 'token'`.

### Impacto

El runtime no arrancaba: sin HttpServer no hay overlay, ni API/WS, ni TUI funcional.

### Causa

`create_plugins()` leía `http_settings.token` como atributo directo. `PluginSettings`
es un `_ExtensibleConfigModel` (`extra="allow"`), así que claves declaradas en `config.toml`
viven en `model_extra` y las no declaradas/no presentes **no existen** como atributo:
`__getattr__` levanta `AttributeError`. `token` no es campo declarado ni estaba en la
config del usuario, así que el acceso directo revienta.

### Solución aplicada

Se usó el `get()` que el propio `_ExtensibleConfigModel` provee — resuelve campo declarado,
`model_extra` o `None`:

```python
token=http_settings.get("token"),
```

### Archivos

`kateto/plugins/system/__init__.py`
