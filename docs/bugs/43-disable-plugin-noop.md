---
id: 43
title: "POST /plugins/{name}/disable es un no-op: responde ok pero no deshabilita"
status: open
severity: high
date: 2026-08-03
component: kateto/plugins/system/http_server.py, kateto/core/manager.py
---

## Síntoma
`POST /plugins/{name}/disable` responde `{"status":"ok"}` (HTTP 200) pero el
plugin **sigue habilitado**: `GET /plugins` muestra `"enabled": true` después
de la llamada. El endpoint de gestión de plugins miente: no se puede
deshabilitar ningún plugin vía HTTP.

## Causa raíz
Firma incorrecta en la llamada. En `http_server.py:140`:

```python
await self._manager.disable_plugin(plugin)   # pasa el objeto Plugin
```

pero `PluginManager.disable_plugin(self, name: str)` espera un **nombre**
(`manager.py:86-89`):

```python
async def disable_plugin(self, name: str) -> None:
    plugin = self._plugins.get(name)          # dict keyed por str
    if plugin is None or not plugin.enabled:  # .get(objeto Plugin) -> None
        return                                # -> no-op silencioso
```

El dict `self._plugins` está keyed por `plugin.name` (str); buscar con un
objeto `Plugin` como key nunca matchea → `plugin is None` → retorno temprano →
no-op. La asimetría: `enable_plugin` (línea 132) SÍ pasa el objeto correcto
porque `manager.enable_plugin(self, plugin: Plugin)` espera un objeto — enable
funciona, disable no.

## Pasos para reproducir
```bash
curl -s -X POST http://127.0.0.1:8080/plugins/audio_output_player/disable
# -> {"status":"ok"}   HTTP:200

curl -s http://127.0.0.1:8080/plugins | python3 -c \
  "import json,sys; [print(p['name'], p['enabled']) for p in json.load(sys.stdin) if p['name']=='audio_output_player']"
# -> audio_output_player True    <- sigue habilitado
```

## Impacto
El dashboard no puede deshabilitar plugins (silenciar voz, apagar el micrófono,
desactivar un executor) vía API. Además, el contrato de error es engañoso:
devuelve éxito cuando no hizo nada, imposibilitando al cliente detectar el
fallo.

## Fix sugerido (1 línea, NO aplicado)
```python
await self._manager.disable_plugin(plugin.name)
```

## Estado
Abierto. Confirmado contra el server en ejecución el 2026-08-03.
