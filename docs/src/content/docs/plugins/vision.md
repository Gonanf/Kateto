---
title: Vision (look-at)
description: Look-at vision plugin — sources, rolling window, periodic opt-in, settings, degraded behaviors, and sidecar.
---

# Vision (`executor_vision` / `look-at`)

Voices that can see. The `static_vision` executor plugin (settings key
`[plugin.executor_vision]`) keeps a rolling frame window and describes it on
demand through the `look-at` skill, plus optional ambient narration for
opted-in voices. No new hard dependencies; everything degrades instead of
crashing the voice loop.

## Sources

| Source | Default | Notes |
|---|---|---|
| `screen` | yes | `mss`/grim/PIL path, falls back to a dummy frame headless |
| `webcam` | opt-in | Lazy `cv2` import; when opencv is absent (or open/read fails) the source is marked unavailable with a reason and describe replies `"webcam unavailable: <reason>"` |

Unknown source values (e.g. `source="projector"`) return an error result
naming the valid sources — never an exception.

## Window semantics

Bounded in-memory deque per source, default 5s at ~1fps (`window_secs`,
`capture_fps`). Frames are JPEG-bounded (max side 640, 128KB cap,
floor-accept — never raise, never drop). Memory-only; never persisted.

A look covers the window as a **sequence, not a moment**: frames are deduped
(PIL dHash, hamming ≤ 8, keep-earliest, always ≥ 1 frame) and described in one
multi-image call, oldest → newest with `t+<offset>s` labels.

The describe prompt is in Spanish and asks for opinion-ready material: a brief
timestamped description plus what stands out most and what changed between the
first and the last frame — never inventing what is not in the images. The VLM
brings the facts; the voice brings the opinion.

## look-at usage

Bare requests with no source ("look at this", "what do you see?") mean
`source="auto"`: every ACTIVE source is described and the sections arrive
fused with labels:

```
--- screen (5s, 4/5 frames) ---
<text>
--- webcam (5s, 3/5 frames) ---
<text>
```

The study-stream case works this way: camera assignments and the screen book
arrive as labeled sections and the model answers from the matching one.
Explicit words ("camera", "webcam" / "screen", "display", "my screen")
select one source.

## Periodic descriptions (opt-in)

Ambient narration every 30s is **off by default**. Per voice:

```toml
[voice.jane]
vision_periodic = true
vision_interval = "30s"
```

Para una cadencia irregular, rango por voz (el tick del scheduler corre al
mínimo; el plugin sortea la espera en `[min, max]` y sólo narra al
alcanzarla — además del portón de imagen repetida, que evita el costo VLM):

```toml
[voice.jane]
vision_periodic = true
vision_interval_min = "20s"
vision_interval_max = "90s"
```

El sorteo se cuantiza a múltiplos del tick (`k * min`), así la espera real
nunca baja del mínimo ni supera el máximo; cada sorteo se ve en el log
(`[vision] next jane narration in 60s (range 20-90s)`). `vision_interval`
sigue como compatibilidad (sin min/max, cadencia fija exacta); con un solo
lado presente el otro toma el mismo valor (fijo); `min > max`, valores `<= 0`
o expresiones inválidas → warning con el valor efectivo y cadencia fija, sin
romper el arranque. La fuente de azar se inyecta en el constructor (`rng`:
`random.Random(seed)` o callable); el `random` global nunca se toca.

One stable job per voice (`vision-describe-<voice>`), canceled on disable;
re-enable never duplicates. Ticks deferred while the voice is talking wait
for the next interval — never re-queued.

Registration is ack-driven: the job counts as scheduled only when the
scheduler's `schedule_result` ack arrives (the `[vision] scheduled ...` line
logs at ack time, never at emit). If vision boots before `executor_scheduler`,
the first request has no subscriber yet and is lost — pending voices retry
with a short backoff until the ack lands, then stop. If the retries run out,
one WARNING names the job (`[vision] vision-describe-<voice> NOT registered
after N attempts (is executor_scheduler enabled?)`).

> Boot-order trap: `PluginManager.enable_plugin` calls `plugin.enable()`
> **before** subscribing its handlers, so any event emitted from `enable()`
> reaches zero receivers and is dropped silently. Never assert side effects
> at emit time — wait for the ack.

## Settings

`[plugin.executor_vision]` keys:

| Key | Default | Meaning |
|---|---|---|
| `source_default` | `"screen"` | Capture source when none given |
| `window_secs` | `5.0` | Rolling window length |
| `capture_fps` | `1.0` | Capture rate |
| `describe_interval` | `"30s"` | Periodic interval expression |
| `vision_endpoint` | unset | Primary OpenAI-compatible endpoint (required for real vision) |
| `vision_model` | unset | Primary model |
| `vision_max_tokens` | `300` | Per describe call |
| `vision_timeout` | `60.0` | Seconds (primary/fallback HTTP links) |
| `max_frames_per_describe` | `2` | Frames per describe: oldest + newest (each costs ~2350 vision tokens, ~36 s prefill at ~66 tok/s) |
| `vision_sidecar_max_width` | `1024` | Max width before sending to the sidecar (aspect kept, JPEG); over-cap frames are dropped with a log |
| `vision_fallback_endpoint` | unset | Local VLM endpoint (llama-server style) |
| `vision_fallback_model` | unset | Fallback model |
| `device_index` | `0` | Webcam device |
| `vision_repeat_hamming_max` | `6` | Max Hamming distance (of 64 dHash bits) to call a periodic window "same screen" and stay silent |
| `vision_repeat_text_min_ratio` | `0.9` | Min caption similarity (difflib ratio) to call a periodic caption "same" and stay silent |

No model name is hardcoded: unconfigured links are skipped, not guessed.

### Fallback chain and `via` values

1. Primary (`vision_endpoint` + `vision_model`) → `via="primary"`
2. video-rag sidecar `describe_images` tool → `via="sidecar"`
3. Direct HTTP to `vision_fallback_endpoint`/`vision_fallback_model` → `via="fallback-vlm"`
4. Metadata recap → `via="recap"`

A 400 from one link tries the next; anything unconfigured is skipped. With
nothing configured the result is a recap starting
`"recap (vision not configured: set vision_endpoint/vision_model or enable
the video-rag sidecar)"`. Connection/timeout errors propagate as bus error
events — the bus stays up.

A periodic tick that lands on `via="recap"` stays silent: no `generate` is
emitted (one warning, then quiet). A direct user ask still gets its "could not
see" reply — that is an answer, not ambient narration.

## Turn framing (bug 121, opinion in bug 123)

The plugin emits the caption bare (`[look-at <source> <span>s]: …`) and the
voice frames it: in `_messages_for` (ambient `generate`) and in
`_remember_event` (requested `vision_describe_result`) the block is wrapped
with a turn instruction in the voice's own `response_language` — own eyes,
opinion in 1-2 sentences in character (what it thinks, what catches its eye,
what it would do or ask), never repeat the literal description, never ask
what to do with it, don't invent. The frame rides the volatile turn (user
message / history); the frozen stable prompt never changes.

## Repeat silence (bug 123)

A periodic tick narrates only what is new. Per source the plugin keeps the
last narrated window (representative frame dHash + caption text):

- Same image: Hamming distance at or below `vision_repeat_hamming_max` →
  no VLM/sidecar call, no narration (`[vision] periodic narration skipped
  for <voice>: imagen repetida (<source>=hamming <d>/<max>)`).
- Same caption with different frames: similarity at or above
  `vision_repeat_text_min_ratio` → the describe result is still emitted but
  no `generate` goes out (`... caption repetido (<source>=similitud
  <r>>=<min>)` with the caption).
- A user-requested look-at always answers, even when the image repeats, and
  refreshes the last-seen window — so the next periodic tick on that same
  screen stays silent.

When the sidecar link misses, the log names the cause: no MCP client
configured (with the startup error when the process failed: missing binary,
handshake, timeout) vs client running without the `describe_images` tool.

### Sidecar timeout and recompression

A native 1920x1080 frame costs the VLM ~2350 vision tokens at ~66 tok/s
prefill (~36 s) plus generation, so the 30 s MCP default always loses. The
sidecar call uses `max(vision_timeout, 120)` seconds — the configured vision
timeout with a 120 s floor that also covers cold model loads — and every call
logs it (`sending N frame(s) (... dropped over cap) with timeout Ts`).
`call_tool_result` / `try_call_tool_result` accept a per-call `timeout`
(default 30.0); only vision overrides it.

Before sending, each frame is squeezed to `vision_sidecar_max_width` (default
1024, aspect preserved) as JPEG (quality ladder 70→55→40, then smaller
scales). The default is measured, not guessed: with the real client 1280 px
still times out (30.01 s), 1024 px answers in ~20 s and 896 px in ~11 s —
vision tokens scale with area, not bytes (recompressing the same 1080p to a
233 KB JPEG still times out). Frames that already fit pass through byte-identical — never
upscaled, never re-encoded for fun. Anything still over the sidecar ~1.5MB
data-URL cap is dropped with a warning and never sent (the sidecar would
reject it); when every frame drops, the sidecar link is skipped with the
reason logged.

At most `max_frames_per_describe` frames travel per describe (default 2: the
oldest and the newest kept frame — what shows the change; capped against the
request's `max_images`). The describe log reports the sent count
(`frames=K/N`).

When periodic vision starts (opt-in voices only), one minimal describe (1x1
image) prewarms the VLM through the configured endpoint or the sidecar, after
a 10 s grace so `external_mcp.start_all()` finishes first. Best-effort: a
failed prewarm logs a warning and nothing else — no error event, no
narration.

## Degraded behaviors

- Empty window on all resolved sources → `"no frames captured yet"`, counts 0.
- Webcam without opencv → `"webcam unavailable: <reason>"`, screen unaffected.
- PIL absent → PNG path still appends; dedupe returns the `max_images` most
  recent untouched.
- `window_secs` ≤ 0 → ctor `ValueError`.

## Existing users: manual step

Bootstrap copies new defaults only for fresh configs. The plugin backfills
the missing `skills/look-at/SKILL.md` file automatically, but it cannot edit
your existing `voice.<name>.skills` lists — add `"look-at"` yourself:

```toml
[voice.jane]
skills = ["orchestrator", "look-at"]
```

Fresh bootstraps already list `look-at` for `jane`, `doktor`, `conquest`,
and `whisperer`.

## Sidecar (video-rag, future wiring)

The `describe_images` sidecar link is live in the fallback chain but the
server entry is BYO and disabled by default. To use it: install the
`video-rag` binary on `PATH` and point it at its own config via
`VIDEO_BASE_URL` / `VIDEO_VISION_MODEL` (the sidecar inherits Kateto's
process env and reads its own `config.toml` — no Kateto config change).
Its hours-ago `search` / `answer` tools are available for a future memory
item and are NOT wired into the live chain here.
