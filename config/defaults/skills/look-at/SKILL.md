# Look At

On-demand eyes for the voice: when the user asks you to look at something, describe the recent action on screen (and webcam when available).

## Source selection

The describe call takes a `source` value. Pick it from the user's words:

- Bare request with no source ("look at this", "what do you see?", "watch me do this") means `source="auto"`: every ACTIVE source is described and the sections arrive fused with source labels. The study-stream case works this way: camera assignments and the screen book arrive as labeled sections and you answer from the matching one.
- Explicit source words select one source: "camera", "webcam", "cam" mean the webcam; "screen", "display", "monitor", "share", "my screen" mean the screen. Anything else is not a source — treat it as a bare request (`source="auto"`).

## Window semantics

A look covers the rolling window (5s default), not a single moment: the description summarizes the SEQUENCE of frames oldest to newest with `t+<offset>s` labels, so "watch me do these steps" arrives as one timestamped narration instead of one random snapshot.

## Periodic descriptions

Ambient narration every 30s is opt-in and off by default: it only runs for voices with `vision_periodic = true` in their voice config. Never promise ongoing watching unless that voice opted in.
