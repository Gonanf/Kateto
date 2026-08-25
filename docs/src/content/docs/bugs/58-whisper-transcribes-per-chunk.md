---
title: "Whisper transcribes every audio_chunk instead of per-VAD-turn"
description: "Symptom"
---


## Symptom
ASR latency and whisper.cpp server load are higher than necessary for the
same phrase length.

## Root cause
`WhisperAudioProcessor.on_audio_chunk` (whisper.py:39) calls
`provider.transcribe(data)` for EVERY `audio_chunk` event from the mic
capture. `WhisperProvider.transcribe` (providers/whisper.py:39) re-encodes
the chunk to WAV and POSTs it to whisper.cpp over HTTP each time.

If the capture emits small chunks (200-500ms), a single spoken phrase becomes
N sequential whisper inferences + N HTTP handshakes instead of 1. Silero VAD
(`plugins/audio_input/silero.py`) is already running and detects speech
boundaries — it is not used to gate transcription.

## Fix (directional, not applied)
Accumulate PCM in the plugin between `on_audio_chunk` calls; only transcribe
when Silero reports end-of-speech (or a max-buffer ceiling). One inference +
one HTTP POST per spoken turn.

## Why it matters
Cheapest latency win on the current (non-omni) pipeline: no model change, no
new dependency, just gate the existing transcribe call on the VAD that is
already running.

## Ceiling
Per-turn transcription still waits for full phrase -> no streaming ASR. If
word-level streaming is wanted later, switch to faster-whisper
(`beam_size=1`, `condition_on_previous_text=False`) or an omni model. YAGNI
for now.
