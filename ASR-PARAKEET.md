# ASR Parakeet (CrispASR) — motor alternativo de STT en Kateto

Añade parakeet (CrispASR) como motor de transcripción **alternativo** al whisper.
No se tocó `whisper.py` ni `kateto/providers/whisper.py`; el motor viejo sigue igual.

## Archivos
- `kateto/providers/parakeet.py` — `ParakeetProvider` (CLI: mismo contrato que providers whisper, `__aenter__`/`aclose`/`transcribe`; escribe WAV temp 16 kHz mono s16le, invoca `-m <modelo> --backend parakeet ... -otxt -of <base>`, timeouts y fail-open), **y** `ParakeetServerProvider` (server: habla con un `crispasr --server` ya levantado vía `POST /v1/audio/transcriptions`, multipart, con `health` opcional al arrancar), **y** `ParakeetStreamProvider` (streaming: abre el binario **una vez** en `__aenter__`, `feed(pcm)` por stdin, lector en tarea aparte que parsea las líneas JSON a `TranscriptionData` vía callback `on_event`; `aclose()` cierra stdin, espera el último `final` con timeout y mata el proceso; fail-open con reinicio acotado `stream_max_restarts` y degradación a no-streaming). Factory `create_parakeet_provider(settings)` que elige por `backend = "server" | "cli" | "stream"`.
- `kateto/plugins/audio_processor/parakeet.py` — `ParakeetAudioProcessor(Plugin)`, capabilities `("transcribe",)`, espejo de whisper (`audio_chunk` → `transcription`). En `enable()` arma el provider por `backend`, y si es `server` proba `/health` (warning claro si no está, sin tumbar el enable). En modo `stream`, `on_audio_chunk` extrae el PCM crudo (`pcm_s16le` directo, `wav` desenvuelto) y lo pasa a `feed()`; el callback `on_event` re-emite cada `partial`/`final` como `transcription` con el flag `partial`. Fail-open: errores se loguean, no se emite evento, el bus sigue vivo.
- `kateto/core/event.py` — `TranscriptionData.partial: bool = False` (ver § Streaming por qué el mismo evento y no uno nuevo).
- `kateto/plugins/audio_processor/__init__.py` — registra `audio_processor_parakeet` (`ctx.plugin_settings(...)`) **sin sacar whisper**. Si falta la sección (config vieja) se omite solo parakeet.
- `kateto/providers/__init__.py` — exporta `ParakeetProvider`, `ParakeetServerProvider`, `create_parakeet_provider`.
- `config/defaults/config.toml` — sección `[plugin.audio_processor_parakeet]` con `backend = "server"` (default) / `"cli"`, `host`/`port`, y `gpu_backend`/`device`/`bin`/`model` (solo CLI).
- `kateto/tests/test_audio_processor_parakeet.py` — 16 tests `@pytest.mark.asyncio`: provider mockeado/binario falso para CLI + camino server vía `httpx.MockTransport` (sin depender de proceso real) + camino streaming con proceso hijo falso (parcial, final, línea basura ignorada, muerte y reinicio, degradación tras el límite, `aclose()` esperando el `final`, y plugin stream de punta a punta en el bus).
- `docs/src/content/docs/plugins/audio-processor.md` — doc del plugin.

## El modo server sí existe (corrección del trabajo anterior)

El reporte previo afirmaba *"El binario es un CLI sin modo servidor/persistente:
carga el modelo en cada invocación"*. **Es falso.** CrispASR tiene modo server
(el modelo queda residente en memoria):

```
crispasr --server --host 127.0.0.1 --port 8098 -m <modelo.gguf> --backend parakeet --gpu-backend vulkan -dev <N>
```

Endpoints (verificados contra el binario 0.8.37):
`POST /inference` · `POST /v1/audio/transcriptions` (OpenAI-compatible, el que usa
este provider) · `POST /load` (hot-swap modelo sin bajar el server) · `GET /health`
· `GET /v1/models` · `GET /backends`. Flags: `--server-workers N` (N× memoria) y
`--ws-port PORT` (ASR en streaming por WebSocket; véase más abajo).

## Activación

Solo **uno** `enabled = true` (ambos suscriben a `audio_chunk`). En
`config/defaults/config.toml`:

```toml
[plugin.audio_processor_parakeet]
enabled = true          # apagar audio_processor_whisper
backend = "server"      # server (recomendado) | cli | stream (ver § Streaming)
motor = "ultra"         # ultra (calidad) | redux (mínimo TTFT); con `server` es informativo
host = "127.0.0.1"
port = 8098
language = "es"         # es para audio en español
timeout = 120.0
# --- solo cli ---
# bin = ".../crispasr"
# model = ""            # p.ej. parakeet-redux-q8_0.gguf
# gpu_backend = "vulkan"
# device = "1"
# --- solo stream ---
# stream_step_ms = 500                # ventana de acumulación: cadencia de parciales
# stream_final_on_silence_ms = 600    # silencio tras habla antes de cerrar el final
# stream_max_restarts = 3             # reinicios del hijo antes de degradar
# stream_final_wait_s = 30.0          # cuánto espera aclose() el último final
```

- **`backend = "server"` (default)**: hay que levantar el proceso **antes** de
  habilitar el plugin. El comando exacto, con el modelo ultra:
  ```
  /run/media/chaos/secundario/proyectos/crispasr/crispasr-linux-x86_64-vulkan/crispasr \
      --server --host 127.0.0.1 --port 8098 \
      -m /run/media/chaos/secundario/proyectos/redux-gguf/models/parakeet-ultra-q8_0.gguf \
      --backend parakeet --gpu-backend vulkan -dev 1
  ```
  Si el server no responde, el provider fail-opens por transcripción (log de error,
  texto vacío, el bus no se cae) y `enable()` loguea un warning con `/health`.
- **`backend = "cli"`**: `motor = "ultra"` → `parakeet-ultra-q8_0.gguf` ·
  `motor = "redux"` → `parakeet-redux-q8_0.gguf`; overrides `bin`/`model`, y el flag
  GPU ahora es `gpu_backend` (el `backend` quedó para la elección de transporte).

## Latencia medida (server arriba, modelo residente, Vulkan dev 1)

Audio sintetizado con espeak (`en`) — WAV de 3.2 s y 21.5 s — transcrito dos veces
seguidas contra el provider server; **la segunda llamada es la representativa**
(modelo ya cálido).

| modo | audio 3.2 s | audio 21.5 s |
|---|---|---|
| **server (modelo residente)** | **0.173 s** | **0.649 s** |

Texto correcto en ambos: 3 s → `"The quick brown fox jumps over the lazy dog."`;
20 s → párrafo de demostración (variante ASR esperable: "Catego"/"terms" por voz
sintética). El costo pasa a ser **proporcional al audio** y no paga ni el arranque
del proceso ni la carga del modelo por turno.

> Comparado con `cli` (invocación nueva), que paga carga de modelo por turno
> (medido antes: ~1.15 s TTFT solo de carga para `ultra`), el `server` gana
> 3–6× en audio corto — el caso del runtime de voz.

## Streaming en vivo (`--stream --stream-json`, implementado)

`backend = "stream"` abre el binario **una vez** y le manda PCM crudo por stdin.
El modelo se carga una sola vez al arrancar el proceso: el costo por turno es
sólo el cómputo del bloque nuevo. Comando exacto que arma el provider:

```
crispasr -m <modelo> --backend parakeet \
    --stream --stream-json --stream-step 500 --stream-final-on-silence-ms 600 \
    --gpu-backend vulkan -dev 1 -np
```

- stdin: **PCM crudo s16le 16 kHz mono** (el plugin extrae el PCM de `AudioData`;
  `pcm_s16le` va directo, `wav` se desenvuelve).
- stdout: **una línea JSON por evento** —
  `{"type":"partial","utterance_id":N,"text":...,"t0":...,"t1":...}` y
  `{"type":"final",...}` (mismo formato, texto cerrado). Una línea que no es
  JSON se loguea y se ignora; los warnings de inicialización van por stderr
  (drenado en tarea aparte para que nunca bloquee al hijo).

### El WebSocket del server NO sirve para parakeet

`crispasr --server ... --ws-port 8099` abre `ws://host:8099/v1/realtime`, pero
para parakeet contesta:

```
{"error":"failed to open stream (whisper-only today)"}
```

Está limitado a whisper. **Descartado** — el streaming de parakeet va por el
proceso hijo `--stream`, no por el server.

### Latencia medida (corrida real, esta tarea)

`ParakeetStreamProvider` (ultra-q8_0, Vulkan dev 1, `step 500` / `silence 600`)
alimentado con los primeros 30 s de `tmp_audio/largo16k.wav` (castellano real)
en trozos de 100 ms a ritmo real:

| hito | tiempo (desde spawn) |
|---|---|
| **primer `partial`** (`"Es cierto, Rodrigo."`) | **2,88 s** (incluye la carga única del modelo) |
| **parciales siguientes** | **uno cada ~0,5 s** (54 parciales en 30 s de audio) |
| **`final`** (texto cerrado de los 30 s) | **11,4 s después del fin del feed** (llega al cerrar stdin en `aclose()`; re-decodifica el segmento completo) |

Muestra de la cadencia (t, tipo, texto): `2.88 partial → 3.07 → 3.57 → 4.15 →
4.67 → … → 29.78 → 30.30` y luego `41.43 final` con el texto completo
(`"Es cierto, Robert, que son primos. … Pero mirá lo que son estas teta,
Mario. RPG del G de Camper."`). Transcripción en castellano correcta y
coherente con el audio durante todo el segmento.

> El 1,05 s medido antes para el primer parcial era con proceso ya cálido; los
> 2,88 s de acá incluyen el arranque en frío (carga del ultra). En el runtime
> el proceso queda abierto, así que el caso cálido es el representativo por
> turno. Con `--stream-step 2000` el primer parcial tarda 2,1 s incluso en
> caliente (peor) — queda 500.

### Contrato con el bus: mismo evento + `partial: bool = False`

Decisión: **un campo opcional en `TranscriptionData` y el mismo evento
`transcription`**, no un evento nuevo `transcription_partial`. Por qué:

1. **Compat total**: quien hoy escucha `transcription` sin pedir nada más sigue
   funcionando igual — los `final` llevan `partial=False` y los parciales se
   filtran opt-in (`if data.partial: return`).
2. **Menos invasivo**: un evento nuevo exigiría registrarlo, actualizar cada
   suscriptor y mantener dos caminos en el gate de fin de turno; con el flag el
   gate (que se hace en otro worktree) escucha el mismo evento y lee parciales
   para decidir antes de cerrar el turno.
3. El modelo ya existe en el bus (`TextChunk`/`AudioOutput` usan `final: bool`);
   `partial` es su espejo para el lado STT.

## Verificación
- `uv run pytest kateto/tests/test_audio_processor_parakeet.py -q` → **16 passed**:
  CLI (provider mockeado + binario falso), server (`httpx.MockTransport`) y
  streaming (proceso hijo falso: parcial/final/basura/reinicio/degradación/`aclose`/plugin).
- E2E real **server**: `ParakeetServerProvider` contra `crispasr --server` (Vulkan,
  ultra) con los dos WAV — ver tabla de latencia arriba; texto devuelto correcto.
- E2E real **stream** (esta tarea, una sola corrida): `ParakeetStreamProvider`
  contra el binario directo (Vulkan dev 1, ultra-q8_0, step 500 / silence 600)
  con 30 s reales de `largo16k.wav` a ritmo real — ver tabla de latencia arriba
  (primer parcial 2,88 s en frío, parciales cada ~0,5 s, final 11,4 s tras EOF).
- El server se levantó solo para verificar y se mató al terminar (ver Limpieza).

## Sin verificar
- No se levantó `uv run kateto run` (sesión del usuario activa); el registro del
  plugin se valida por tests de bus/discovery, no por arranque end-to-end.
- Hot-swap (`POST /load` ultra↔redux) no ejercitado desde el provider.
- Sin resampleo: se asume PCM s16le 16 kHz mono (lo que emite el mic); otras tasas
  no se convierten (ponytail).
- Calidad con voz real (no sintética) y cuántos turnos mantiene la latencia baja
  sin reiniciar no se caracterizaron.
- El `final` tras EOF tardó 11,4 s en un segmento de 30 s continuos; con turnos
  cortos de voz (2–5 s) debería ser proporcionalmente menor, no medido.

## Limpieza
El proceso `crispasr --server` que se levantó para esta verificación quedó **apagado**
al terminar (no queda modelo cargado en GPU). El proceso `crispasr --stream` de la
corrida real también quedó **apagado** (`aclose()` + `pgrep` verificado).
