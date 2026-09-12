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

One stable job per voice (`vision-describe-<voice>`), canceled on disable;
re-enable never duplicates. Ticks deferred while the voice is talking wait
for the next interval — never re-queued.

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
| `vision_timeout` | `60.0` | Seconds |
| `vision_fallback_endpoint` | unset | Local VLM endpoint (llama-server style) |
| `vision_fallback_model` | unset | Fallback model |
| `device_index` | `0` | Webcam device |

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
