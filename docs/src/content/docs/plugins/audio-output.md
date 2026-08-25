---
title: Audio Output
description: Audio Output — documentación de Kateto.
---

# Audio Output (TTS) Plugins

Text-to-speech engines. Each engine is an independent plugin.

## Data Plane

TTS plugins receive tokens and produce PCM audio through **AudioPipeline queues** (`token_queue` and `pcm_queue`), not the event bus. This keeps streaming data off the bus for low-latency playback.

## Modules

- `edgetts.py` — Microsoft Edge TTS (free, no API key)
- `camb.py` — Camb TTS engine
- `zonos.py` — Zonos TTS with speaker embeddings
- `player.py` — PCM audio playback
- `base.py` — Base audio output class

## Plugins

### `audio_output_zonos` (P0)
Zonos TTS engine with speaker embeddings for voice consistency.

- Uses **Zonos2 / Zonos0.1** via local HTTP server (zonos2.cpp)
- Speaker embeddings ensure consistent voice timbre per agent
- **Reference voice clips required** — each agent needs a short sample for Zonos to synthesize their voice
- Streams sentence-by-sentence PCM chunks to the player

**Voice selection:** The TTS plugin determines which voice to use based on `source` and `subsource` of the event. The event contract can optionally include a `voice_id` for greater granularity.

### `audio_output_player` (P0)
Playback plugin. Receives PCM chunks from TTS and plays them through the system audio output.

**Receives:** PCM s16LE audio chunks (streaming)
**Reacts to:** `interrupt` — stops playback immediately

### `audio_output_edgetts` (P0)
Microsoft Edge TTS — free, no API key required. Good quality cloud TTS.

### `audio_output_camb` (P1)
Camb TTS engine.
