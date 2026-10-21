# MASK-5 — Report

## Qué se creó

- `kateto/mask/__init__.py` — exporta `MASK_PROTOCOL = 1` y `MaskAudioBridge`.
- `kateto/mask/audio_bridge.py` — puente servidor→teléfono. `MaskAudioBridge` expone
  `serve(ws)`, `register`, `unregister`, `frame_for` (puro) y los handlers
  `on_audio_output` / `on_interrupt` listos para el bus.
- `kateto/mask/web/browser-pcm-player.js` — player WebAudio del teléfono (ESM, sin deps,
  sin DOM top-level). Decodifica `pcm_s16le`, remuestrea al `sampleRate` del contexto y
  agenda los chunks en serie con `leadMs` y tope `maxQueueMs`.
- `kateto/mask/web/browser-pcm-player.test.mjs` — 10 tests `node:test` con fakes de
  `AudioContext`.
- `kateto/tests/test_mask_audio_bridge.py` — 13 tests pytest-asyncio, incluido el roundtrip
  real con `uvicorn.Server` + `websockets`.

## Protocolo (servidor → teléfono)

### Frame de audio (`frame_for` / `on_audio_output`)

| Campo | Tipo | Notas |
|---|---|---|
| `event` | str | `"audio_output"` |
| `type` | str | `"audio"` |
| `protocol` | int | `1` (`MASK_PROTOCOL`) |
| `voice_id` | str \| null | |
| `sample_rate` | int | rate de los samples (22050 / 24000) |
| `channels` | int | |
| `format` | str | `"pcm_s16le"` (raw LE 16-bit mono) |
| `seq` | int | `data.sequence` |
| `final` | bool | cierra el turno |
| `audio_b64` | str | base64 stdlib de `samples` (`""` si vacío) |
| `n_bytes` | int | `len(samples)` |
| `rms` | float 0..1 | `data.rms` o `calculate_raw_rms(samples)`, clampeado |
| `is_speaking` | bool | `rms > 0.05 and not final` |
| `text` | str \| null | |
| `words` | list \| null | `[{text, start_ms, end_ms}]` |
| `t_ms` | int | `int(time.monotonic() * 1000)` (marca de envío) |

### Frame de interrupción (`on_interrupt`)

| Campo | Tipo | Notas |
|---|---|---|
| `event` | str | `"interrupt"` |
| `type` | str | `"interrupt"` |
| `protocol` | int | `1` |
| `reason` | str | `data.reason` |
| `dept` | str \| null | `data.dept` |

### Frame de registro (`register`)

`{"event": "mask_ready", "type": "ready", "protocol": 1}`.

## Cómo lo cuelga MASK-2

Las 2 líneas exactas a agregar en `kateto/plugins/system/http_server.py`:

```python
@app.websocket("/ws/mask")
async def mask_ws(ws: WebSocket) -> None:
    await mask_bridge.serve(ws)
```

(`mask_bridge = MaskAudioBridge()` como singleton; el bus despacha `on_audio_output` /
`on_interrupt` a los suscriptores.)

## Qué NO se pudo verificar

- Reproducción en un teléfono real (bocina/latencia real, gesto de desbloqueo).
- Caudal de chunking con audio TTS real (piper/edge_tts/boson) — los tests usan PCM sintético.

## Gates

```
PATH=/home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin:$PATH PYTHONPATH=. \
  /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin/python -m pytest kateto/tests/test_mask_audio_bridge.py -q
```

```
cd kateto/mask/web && node --test browser-pcm-player.test.mjs
```
