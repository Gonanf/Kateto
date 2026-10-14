---
id: 100
title: "/events/stream descartaba en silencio todo evento con bytes (el audio nunca salía)"
severity: Alta
status: resolved
component: kateto/plugins/system/http_server.py
resolved: 2026-10-14
---

## 100. /events/stream descartaba en silencio todo evento con bytes (el audio nunca salía)

**Severidad:** Alta
**Componente:** `kateto/plugins/system/http_server.py`

### Descripción

El observer de `/events/stream` armaba el payload con `envelope.data.model_dump()` y lo mandaba
con `asyncio.get_event_loop().create_task(ws.send_json(payload))`. Para cualquier evento con
`bytes` crudo, `send_json` reventaba:

```
$ python -c "import json; from kateto.core.event import AudioOutput; d=AudioOutput(samples=b'\x00\x01'*4000, sample_rate=22050, channels=1, format='pcm_s16le', voice_id='jane'); print(json.dumps({'name':'audio_output','data':d.model_dump()}))"
TypeError: Object of type bytes is not JSON serializable
```

Idem `AudioData.samples` (`audio_chunk`) y `VisionFrameData.frame`. Como la excepción moría
dentro de la task fire-and-forget, nadie la veía: el frame se perdía sin log.

### Impacto

`/events/stream` entregaba `text_chunk` y `audio_output_status`, pero **cero** `audio_output`.
Medido contra el runtime vivo inyectando un turno por `POST /events/send`: el audio del turno
nunca salía por el WS, mientras que el mismo turno por `/ws/overlay` sí entregaba PCM
(`event=audio_output final=False rms=0.00155 audio_len=141996`). Es decir: el audio existe y
se emite, `/events/stream` lo tira. Sin egress de audio no se puede medir TTFAB, así que el
CSV de latencia no podía atribuir pipeline vs red.

### Causa

Doble. Uno: el payload no es JSON-serializable (bytes y datetimes crudos). Dos: el envío se
hace en una task sin `try/except` ni logging, así que el `TypeError` se pierde.

**Solución aplicada:**

1. Helper privado `_json_safe()` en `http_server.py`: los bytes salen como base64 ascii bajo
   `<clave>_b64` (`samples` → `samples_b64`, `frame` → `frame_b64`) con `encoding: "base64"`, y
   los `datetime` como ISO. No se tocó `core/event.py` ni los modelos.
2. Envío secuencial por observer en una sola task, para que el orden de los frames sea
   determinista.
3. Enmarcado de turno por voz: `turn_start` antes del primer `audio_output` con samples no
   vacíos y `turn_end` al cerrarse (`final` o `stale` a los 2 s), que es lo que permite medir
   `pipeline_ms` y `red_ms`.

**Archivos:** `kateto/plugins/system/http_server.py`, `kateto/tests/test_http_audio_egress.py`, `script/qa/mask1_egress_client.py`, `docs/src/content/docs/runtime/audio-egress.md`
