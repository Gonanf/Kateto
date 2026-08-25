---
title: "WS /events/stream: payloads no serializables (bytes de audio) pierden el frame silenciosamente; sin backpressure"
description: "Síntoma"
---


## Síntoma
El observer de eventos del WS (`http_server.py:158-174`) hace
`create_task(ws.send_json(payload))` fire-and-forget por cada evento. Dos
defectos:

1. **Payloads no JSON-serializables pierden el frame en silencio.** Los eventos
   de audio (`audio_output`, `audio_chunk`) llevan `samples: bytes`
   (`core/event.py:75`, `core/event.py:38`; `edgetts.py:131` emite
   `samples=bytes(pcm_buffer)`). `envelope.data.model_dump()` conserva
   `samples` como `bytes` → `send_json` lanza `TypeError: Object of type bytes
   is not JSON serializable` **dentro de la task**, no en el bucle del observer.
   La excepción se traga (asyncio solo registra "Task exception was never
   retrieved"), el frame nunca llega y la limpieza de ws muertos nunca corre.
2. **Sin backpressure.** Cada evento crea una task nueva sin esperarlas ni
   retenerlas. Un cliente lento + ráfaga sostenida acumula tasks sin límite por
   conexión (memoria) y no hay cola por conexión que permita throttling.

## Causa raíz
`http_server.py:170`:

```python
asyncio.get_event_loop().create_task(ws.send_json(payload))
```

- `create_task` no lanza por errores de envío (solo por falta de event loop),
  así que el `except Exception: dead.append(ws)` (líneas 171-172) es código
  muerto para el caso de envío: la excepción ocurre asíncronamente en la task.
- El resultado de `model_dump()` con `bytes` no pasa por `json.dumps` de
  `send_json`. Verificado con el modelo real:
  `json.dumps(AudioOutput(...).model_dump())` →
  `TypeError: Object of type bytes is not JSON serializable`,
  `type(model_dump()['samples']) is bytes`.
- Un WS que muere a mitad de envío queda para siempre en `self._observers`
  (el `finally` del handler de conexión sí lo quita, pero el fallo de send
  dentro de la task no llega ahí).

## Pasos para reproducir
Con un cliente WS conectado a `ws://127.0.0.1:8080/events/stream`, emitir un
evento cuyo `data` contenga bytes (p.ej. `audio_output` con `samples`) — el
frame no llega y no hay error visible para el cliente:

```bash
# 1. cliente WS conectado (handshake 101 OK)
# 2. el server emite un evento de audio (audio_output/audio_chunk con bytes)
# 3. el cliente no recibe nada; el log del server a lo sumo muestra
#    "Task exception was never retrieved"; el WS no se marca como muerto
```

Proceso aislado que reproduce la excepción del send con el modelo real de
Kateto:

```python
from kateto.core.event import AudioOutput
json.dumps(AudioOutput(samples=bytes(3200), sample_rate=16000, channels=1).model_dump())
# TypeError: Object of type bytes is not JSON serializable
```

Contraste (control): con `text_chunk` (JSON-safe), una ráfaga de 50 eventos
hacia un cliente lento (10 ms/frame) entrega 50/50 en orden — la entrega
funciona solo mientras el payload sea serializable y la carga no sature.

## Impacto
- Con audio activo (uso normal: TTS/STT), ningún frame de audio llega al
  dashboard vía WS. El streaming de eventos es la única vía de observación en
  vivo (GET /events está roto, ver bug 42), así que el dashboard ve "nada".
- Clientes lentos o ráfagas pueden acumular tasks sin límite.

## Fix sugerido (NO aplicado)
- Serializar con un encoder tolerante a bytes: `data=json.dumps(payload,
  default=lambda o: o.decode("latin1") if isinstance(o, bytes) else ...)` y
  `ws.send_text(...)`, o convertir `samples` a base64 antes de `model_dump()`.
- Encolar por conexión con backpressure (p.ej. `asyncio.Queue` por WS + una
  task consumidora con `await`, descartando frames si la cola excede un límite
  en vez de crear tasks infinitas).
- Retener las tasks y registrar/recuperar sus excepciones en vez de
  fire-and-forget.

## Estado
Abierto. Defecto de payload confirmado con el modelo real (reproducción
aislada); el patrón de pérdida se dispara en producción cada vez que un evento
de audio fluye hacia un observador WS. Sin audio activo en el entorno headless
no se pudo observar la pérdida en el server vivo (log sin "never retrieved"),
pero el código garantiza el fallo: el body de `send_json` no puede serializar
bytes.
