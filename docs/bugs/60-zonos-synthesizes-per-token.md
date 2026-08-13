---
id: 60
title: ZonosAudioOutput synthesizes TTS per token, not per phrase
severity: low
area: plugins/audio_output/zonos.py
status: open
---

## Symptom
TTS prosody can be choppy and per-segment synthesis overhead is higher than
necessary; first audio may lag if tokens are tiny.

## Root cause
`ZonosAudioOutput._run_pipeline_consumer` (zonos.py:81-101) consumes
`pipeline.token_queue` and for EACH token calls
`self._provider.stream_sentence(TextChunk(text=token, ...))`. The token queue
is fed by the LLM stream (sub-word pieces). So Zonos gets fragments like
"pla" / "nning" as separate synthesis requests, resetting its context window
each time instead of synthesizing a coherent phrase.

`ZonosProvider` itself DOES stream PCM incrementally once given a sentence
(`_stream_sentence` -> `aiter_bytes`, zonos.py:115), so the TTS pipeline is
already incremental — the problem is the granularity of what it is handed.

## Fix (directional, not applied)
Buffer tokens up to a sentence/phrase boundary (punctuation or max token
count) before calling `stream_sentence`. The player still receives PCM
incrementally because `stream_sentence` yields per chunk.

## Why it matters
Better prosody + fewer synthesis calls, while keeping the incremental PCM
stream that already reaches the speaker. No model change.

## Ceiling
Phrase-boundary buffering adds a small delay equal to one token's worth of
text. Acceptable. If word-level streaming TTS is required later, use a
streaming TTS that accepts token deltas natively.
