# Executor Plugins

Executors decide **when and how** to run AI agents. Agents are **batch** plugins — they accumulate events in their queue and only process when they receive a `generate` event. Executors are the ones that emit `generate`.

## executor_classifier (P0)

Uses **mmBERT** fine-tuned to GGUF (via HTTP to llama.cpp) to classify transcribed text.

### Three-Way Classification

| Category | Meaning |
|---|---|
| `EXECUTE` | Directed at the system — route to agents |
| `IGNORE_SELF_TALK` | User talking to themselves |
| `IGNORE_THIRD_PARTY` | Conversation not meant for the system |

### v1 Behavior
On `EXECUTE`, emits `generate` to ALL active voices. Voices self-filter by relevance since per-voice routing (VoiceClassifier) is P1.

Context window: up to 10 previous messages for classification context.

### Fine-Tuning
mmBERT is fine-tuned with a custom dataset, converted to GGUF, and served via llama.cpp.

## executor_interrupt (P0)

Listens for the `interrupt` event from audio input and forwards it to appropriate plugins. Also manages post-interruption resumption.

| Reacts On | Action |
|---|---|
| `on_interrupt` → TTS | Stop playback immediately |
| `on_interrupt` → LLM Agent | Cancel current generation via `asyncio.Task.cancel()` |
| `on_interrupt` → Other | Per-plugin implementation |

After interruption, the audio input resumes listening and the conversation loop restarts from the top.

## executor_voice_classifier (P1)

Optional. Runs after the main Classifier (or standalone, but doesn't work 100% without it). Determines **which voice/agent** should respond.

Requires fine-tuned models with training data from `Voices/{name}/training/`.

## executor_todo_list (P0)

Detects when there is a need to organize tasks into a structured project plan.

### MVP file contract

The shipped MVP has one TODO file per voice: `config/kateto/voices/{voice}/TODO.md`.
The executor creates or updates that file using Markdown task entries in the form
`- [ ] task` or `- [x] task`. It does not create project subdirectories, maintain
global TODO files, or treat `TODO.md` as the canonical backlog. The backlog remains
the source of truth for backlog items; a completed TODO emits `todo_completed` so
the backlog integration can synchronize it.

### Flow

1. An `EXECUTE` classification is parsed for a supported task or completion command.
2. The matching voice's `config/kateto/voices/{voice}/TODO.md` is read and updated
   idempotently.
3. `todo_updated` is emitted for a change; completing an existing task also emits
   `todo_completed` for backlog synchronization.

## executor_random_talk (P2 — Postergated)

Randomly selects an agent to speak about what's in its queue or journal.

## executor_podcast (P2 — Postergated)

Gets a topic (from a plugin or user via TUI) and puts all voices to converse automatically.

## Complete Flow (v1)

```
User speaks → AudioInput records → detects silence → emits audio_chunk
  → AudioProcessor (Whisper) transcribes → emits transcription
  → Executor Classifier classifies intent
    → If EXECUTE: emits generate for Jane/Doktor/Conquest
  → VoiceAgent receives generate, processes queue, streams text
    → Text goes to TTS (Zonos) for audio output
    → Text also emitted as event for other voices to know
  → If user interrupts: AudioInput emits interrupt
    → TTS stops, LLM cancelled, loop restarts
```
