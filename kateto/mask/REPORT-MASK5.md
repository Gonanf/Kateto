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

## Delta: contrato real de /ws/mask

### Campos aceptados ahora en `enqueueFrame`

| Campo base64 | Fuente |
|---|---|
| `audio_b64` | frame legacy del puente (`MaskAudioBridge.frame_for`) |
| `audio` | frame real de `visual_overlay_plugin.on_audio_output` (tipo `viseme`) |

La lectura es `frame.audio_b64 ?? frame.audio ?? null`. Si ninguno está presente y `final` no es `true`, el frame se descarta sin encolar y sin lanzar excepción.

### Discriminante `handleMessage`

```js
// antes — sólo type: "audio"
msg.event === "audio_output" && msg.type === "audio"

// ahora — también type: "viseme"
msg.event === "audio_output" && (msg.type === "audio" || msg.type === "viseme")
```

### Ejemplo del frame real de `/ws/mask`

```json
{
  "event": "audio_output",
  "type": "viseme",
  "voice_id": "jane",
  "rms": 0.12,
  "is_speaking": true,
  "jawOffsetX": 0, "jawOffsetY": 1.2, "jawRotation": 3, "headOffsetY": 0,
  "text": "hola",
  "audio": "<base64 pcm_s16le>",
  "words": [{"text": "hola", "start_ms": 0, "end_ms": 200}],
  "sample_rate": 22050, "channels": 1, "format": "pcm_s16le", "final": false,
  "data": { "...": "copia de los mismos campos" }
}
```

### Frame `update_viseme` (sin audio) — se ignora

`visual_overlay_plugin.update_viseme()` emite también `type: "viseme"` pero sin campo `audio` ni `audio_b64`. Este frame es descartado limpiamente (`"ignored"`) sin encolar ni lanzar excepción.

### `onFrame` y el jaw del avatar

`_scheduleEntry` sigue llamando `onFrame` con `{ voiceId, rms, seq, playbackStartMs, durationMs, text }`. El `rms` proviene de `frame.rms` (presente en los frames viseme), por lo que `kateto-avatar` recibe el valor correcto para animar el jaw.

### Resultado de los tests

```
node --test browser-pcm-player.test.mjs
tests 16 · pass 16 · fail 0
```

10 tests anteriores: todos siguen pasando sin modificación.  
6 tests nuevos: todos pasan.

### Qué no se pudo verificar

- Reproducción en teléfono real con el endpoint `/ws/mask` activo (requiere servidor corriendo y cliente móvil).
- Sincronía jaw ↔ audio sobre red con latencia real (Wi-Fi/LTE).
- Comportamiento cuando `data` contiene campos duplicados con valores distintos a los del nivel raíz.
