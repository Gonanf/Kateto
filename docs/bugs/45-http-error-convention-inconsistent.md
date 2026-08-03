---
id: 45
title: "Convención de errores HTTP inconsistente: errores como 200+{\"error\":...} vs 500 real"
status: open
severity: low
date: 2026-08-03
component: kateto/plugins/system/http_server.py
---

## Síntoma
La API mezcla dos convenciones de error incompatibles:

- **200 + body `{"error": "..."}`**: `POST /events/send` (evento desconocido o
  data inválida) y `POST /plugins/{name}/enable|disable` (plugin no encontrado)
  devuelven HTTP **200** con un body JSON `{"error": "..."}`.
- **500 real**: `GET /events` devuelve HTTP **500** con body plano
  `Internal Server Error` (ver bug 42) — un crash, no un error modelado.

Un cliente que detecte fallos por status code HTTP (lo normal) interpretará
`{"error": ...}` como éxito y solo verá el 500 de `/events`; un cliente que
parseé el body esperará JSON y recibirá texto plano en el 500.

## Causa raíz
Los handlers de aplicación devuelven dicts de error como respuestas 2xx por
defecto (FastAPI serializa el dict con status 200). Los errores de framework
(crash no capturado) producen el 500 plano de la ExceptionMiddleware. No hay
una capa central de mapeo de errores: cada handler decide su propia convención.

- `http_server.py:111` `return {"error": f"unknown event: {request.event_name}"}`
- `http_server.py:116` `return {"error": f"invalid data: {exc}"}`
- `http_server.py:134` `return {"error": f"plugin not found: {name}"}`
- `http_server.py:142` `return {"error": f"plugin not found: {name}"}`
- vs. `http_server.py:68-80` `list_events` sin manejo de errores → 500 plano.

## Pasos para reproducir
```bash
# Error modelado como 200:
curl -s -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/events/send \
  -H 'Content-Type: application/json' -d '{"event_name":"evento_inexistente","data":{}}'
# -> {"error":"unknown event: evento_inexistente"}
# -> HTTP:200

curl -s -w "\nHTTP:%{http_code}\n" -X POST http://127.0.0.1:8080/plugins/no_existe/disable
# -> {"error":"plugin not found: no_existe"}
# -> HTTP:200

# Error real:
curl -s -w "\nHTTP:%{http_code}\n" http://127.0.0.1:8080/events
# -> Internal Server Error
# -> HTTP:500
```

## Impacto
El cliente (dashboard) no puede distinguir éxito de error de forma uniforme.
`{"error": ...}` con 200 fuerza a inspeccionar el body en cada llamada; el 500
plano rompe cualquier parser JSON. Dificulta el manejo de errores y el
diagnóstico.

## Fix sugerido (NO aplicado)
- Devolver códigos 4xx/5xx reales con body JSON uniforme, p.ej.
  `JSONResponse(status_code=404, content={"error": ...})` para evento/plugin
  desconocido y `422` para data inválida.
- Envolver los handlers en una capa de exception handling que devuelva
  `500 {"error": {"type": ..., "message": ...}}` JSON en vez del body plano
  de FastAPI.

## Estado
Abierto. Confirmado contra el server en ejecución el 2026-08-03.
