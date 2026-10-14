---
title: Egress de audio (/events/stream)
description: "Contrato de ws://<host>:<port>/events/stream: cómo recibir el audio de un turno y medir TTFAB."
---

# Egress de audio (`/events/stream`)

`/events/stream` es el canal de **salida de audio** y de eventos del bus. Antes del bug 100
descartaba en silencio todo evento con `bytes` (el `TypeError` pasaba dentro de una task
`create_task` sin dejar rastro), así que el audio nunca salía por acá aunque `/ws/overlay` lo
recibiera sin problema. Hoy el PCM viaja como base64 y cada turno va enmarcado.

## Transporte

- **Endpoint**: `ws://<host>:<port>/events/stream` (WebSocket).
- Un evento JSON por frame de texto. Sin compresión (`permessage-deflate` off), sin canal binario.
- El servidor empuja (`push`); el cliente sólo tiene que estar conectado. No hay subscribe
  por topic: se ve todo el bus, igual que `/ws/overlay`.

## Framing

Un turno de voz son tres tipos de frame, en este orden:

1. **`turn_start`** — control, inmediatamente **antes** del primer frame de audio del turno.
2. **`audio_output`** — uno por chunk de PCM.
3. **`turn_end`** — cierre, inmediatamente después del último `audio_output` con `final: true`.

| Campo | Dónde | Tipo | Unidad |
|---|---|---|---|
| `turn_id` | `turn_start`, `turn_end` | string (hex uuid4) | — |
| `voice_id` | los tres | string | — |
| `trigger` | `turn_start` | string \| null | nombre del evento que abrió el turno (`audio_chunk`, `text_chunk`) |
| `encoding` | `turn_start`, `audio_output` | string | `"base64"` |
| `format` | `turn_start`, `audio_output` | string | `"pcm_s16le"` |
| `sample_rate` | `turn_start`, `audio_output` | int | Hz |
| `channels` | `turn_start`, `audio_output` | int | — |
| `t_in_audio` | `turn_start` | float \| null | unix epoch (s), reloj del server |
| `t_first_audio_byte` | `turn_start` | float | unix epoch (s), reloj del server |
| `sequence` | `audio_output` | int | contador del chunk dentro del turno |
| `final` | `audio_output` | bool | `true` = último chunk |
| `samples_b64` | `audio_output` | string | base64 ascii del PCM crudo |
| `t_turn_end` | `turn_end` | float | unix epoch (s), reloj del server |
| `frames` | `turn_end` | int | frames `audio_output` del turno, incluido el sentinel `final` con PCM vacío |
| `bytes` | `turn_end` | int | bytes de PCM del turno (ya decodificado, sin contar base64) |
| `reason` | `turn_end` | string | `"final"` (llegó el `final: true`) o `"stale"` (2 s de silencio) |

Nunca viaja la clave `samples` cruda: el PCM va en `samples_b64` con `encoding: "base64"`.
Los `samples_b64` vacíos son el sentinel de cierre: no abren turno, sólo cierran el que hubiera
abierto.

## Chunking

PCM **s16le mono**; el `sample_rate` viene en cada frame. Los chunks son del tamaño que emite
el TTS (medido: 141996 chars de base64 ≈ 106 KB ≈ 1 s a 22050 Hz), **no** de un tamaño fijo: el
cliente se guía por `sequence` y por `final`, nunca por la longitud del chunk.

## Cierre de turno

El turno termina con el `audio_output` que trae `final: true`, y enseguida el `turn_end`. Si
el audio se corta a mitad de frase, el servidor lo cierra igual con `reason: "stale"` al llegar
el siguiente chunk después de 2 s de silencio.

## Atribución de latencia

- `pipeline_ms = t_first_audio_byte - t_in_audio` — tiempo del server entre la entrada que
  disparó el turno y el primer byte de audio. **Excluye la red.**
- `red_ms = t_client_recv_first_audio - t_first_audio_byte` — red + scheduling del cliente.
- `t_in_audio` es el timestamp del evento de entrada que disparó el turno (`audio_chunk` real o
  `text_chunk` inyectado), con el reloj del server. Si no hubo trigger en los 5 s previos,
  `t_in_audio` es `null` y `pipeline_ms` no es calculable.

Todos los `t_*` son unix epoch del **mismo** host (el server). Entre hosts distintos sólo se
comparan deltas calculados en un host, nunca la resta de dos timestamps de relojes ajenos.

## Turno caliente vs frío

El prefill del LLM es de 10-11 s la primera vez que habla una voz en la sesión y **contamina**
el TTFAB: ese primer turno mide prefill, no pipeline. Un turno frío (voz sin turno previo en
la sesión) no es comparable con uno caliente.

- El contrato mide el **turno caliente** como métrica de pipeline.
- El CSV tiene que marcar cuál es cuál (`turn_index_voice` del cliente: `1` = el primero que ve
  el cliente en esa sesión).

## Comando que lo reproduce

```bash
./.venv/bin/python script/qa/mask1_egress_client.py --port 8099
```

Requiere un runtime levantado **con el parche aplicado**. Contra un `:8099` de master sin
parche devuelve 0 frames de audio y sale 1: eso es el bug, no el contrato.

## Lo que NO cubre

- Celular / NDK.
- Opus u otro códec comprimido (el wire es base64 sobre PCM crudo).
- `/ws/overlay`, que queda como está: sigue siendo el canal del overlay, no este contrato.
