---
title: "GET /events devuelve HTTP 500 (AttributeError en http_server.py:78)"
description: "Síntoma"
---


## Síntoma
`GET http://127.0.0.1:8080/events` devuelve **HTTP 500 Internal Server Error**
con body plano (no JSON), rompiendo por completo el endpoint de descubrimiento
de eventos del dashboard. El fallo es incondicional: cualquier registro de
evento con ≥1 receptor rompe el endpoint entero.

## Causa raíz
`kateto/plugins/system/http_server.py:78` en `list_events`:

```python
receivers=[r.name for r in reg.receivers],
```

`EventRegistration.receivers` es `tuple[str, ...]` (NOMBRES de plugin, no
objetos): `kateto/core/manager.py:133` construye
`receivers=tuple(plugin_name for plugin_name, _ in self._subscribers.get(name, ()))`.
Por tanto `r` es un `str` y `r.name` lanza `AttributeError: 'str' object has no
attribute 'name'`. No hay `try/except` en el handler, así que FastAPI devuelve
500 plano.

## Pasos para reproducir
```bash
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:8080/events
# -> Internal Server Error
# -> HTTP:500

# Traceback en el log del server:
#   File ".../kateto/plugins/system/http_server.py", line 78, in list_events
#     receivers=[r.name for r in reg.receivers],
#   AttributeError: 'str' object has no attribute 'name'
```

## Impacto
El dashboard no puede listar eventos ni sus contratos vía API. Es además la
única vía pública de inspección del historial de eventos (ver bug 44: sin este
endpoint no hay forma de observar qué emite el sistema salvo por WS).

## Fix sugerido (1 línea, NO aplicado)
```python
receivers=list(reg.receivers),
```
El modelo `EventListItem.receivers` ya es `list[str]`, así que basta con pasar
la tupla tal cual.

## Estado
Abierto. Confirmado contra el server en ejecución el 2026-08-03.
