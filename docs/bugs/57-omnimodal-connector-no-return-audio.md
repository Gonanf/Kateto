---
id: 57
title: OmnimodalConnectorPlugin never receives server audio (recv loop missing)
severity: high
area: plugins/audio_processor/omnimodal_connector.py
status: open
---

## Symptom
The omnimodal speech-to-speech path (fastest architecture: bypasses
whisper+LLM+zonos handoff) emits mic audio to the server via `on_audio_data`
but the server's return audio never reaches the event bus. No `audio_output`
is produced, so the user hears nothing.

## Root cause
`handle_server_event` (omnimodal_connector.py:123) parses
`response.audio.delta`, `response.text.delta`, transcription and tool-call
events and emits them onto the bus. But:

- `handle_server_event` is a plain method, NOT an `on_*` subscriber, and
  nothing in the codebase calls it.
- `OmnimodalConnectorPlugin` has no background task that reads the websocket
  stream from `self._session` and dispatches incoming frames to
  `handle_server_event`.

The send side (`on_audio_data` -> `send_audio_chunk`) works; the receive side
does not exist. The plugin's `capabilities` include `audio_output` but it can
never produce it.

## Fix (directional, not applied)
Add a `_recv_loop` task started in `enable()`, reading server frames and
calling `self.handle_server_event(frame)` per message. Wire cancellation in
`disable()`. The session protocol (`RealtimeSessionProtocol`) needs a
`receive()` coroutine returning decoded event dicts.

## Why it matters
This is the highest-impact latency fix in Kateto: completing the return path
removes the 3-server handoff (whisper -> LLM -> zonos) entirely. Until then
the omni path is a silent no-op and the slow pipeline is the only working one.

## Ceiling
Assumes the server speaks OpenAI Realtime schema (`response.audio.delta` etc).
If MiniCPM-o / llama.cpp-omni uses a different frame shape, map in
`handle_server_event` only — do not add a second protocol class.
