# Audio Output (TTS) Plugins

Text-to-speech engines. Each engine is an independent plugin.

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

### `audio_output_qwen` (P2 — Postergated)
QwenTTS engine. Postergated (discarded due to voice inconsistency).

### `audio_output_llama` (P2 — Postergated)
llama.cpp TTS engine. Postergated.
