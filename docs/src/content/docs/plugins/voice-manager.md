---
title: Voice Manager
description: Voice Manager — documentación de Kateto.
---

# VoiceManager

Routes classifier output to the appropriate voice plugin.

## Purpose

The VoiceManager (`kateto/plugins/system/voice_manager.py`) sits between the classifier and voice agents. Instead of the classifier broadcasting `generate` to all voices, it targets `voice_manager`, which picks ONE voice and emits `speak` to it.

This solves three problems:
- Multiple voices responding simultaneously
- All voices saying the same thing
- Serial TTS sounding identical

## Routing Logic

1. Receives `generate` event from classifier (EXECUTE intent)
2. Filters voice pool by **enabled status** and **capabilities** declared in `VoiceProfile`
3. Picks ONE voice via **weighted random** (configurable in `config.toml`)
4. Emits `speak(target=chosen_voice)` to the selected voice
5. Tracks `speaking_state` via voice_status and voice_idle events

## Configuration

```toml
[plugin.voice_manager]
enabled = true
voice_probabilities = { jane = 0.7, doktor = 0.15, conquest = 0.1 }
```

## Capabilities

Each voice declares capabilities in its `VoiceProfile`:

| Voice | Capabilities |
|-------|-------------|
| jane | orchestration, coordination, general |
| doktor | planning, backlog, risk |
| conquest | agile, ceremonies, process |

The VoiceManager uses these for eligibility filtering. A voice without capabilities matching the input is excluded from the pool.

## Events

| Event | Direction | Purpose |
|-------|-----------|---------|
| `generate` | inbound | Classifier sends intent to route |
| `speak` | outbound | Selected voice receives speak request |
| `speaking_state` | outbound | Broadcasts who is currently speaking |
| `voice_status` | inbound | Tracks voice state changes |
| `voice_idle` | inbound | Tracks when voices finish |
| `voice_enable` | inbound | Enable/disable voices dynamically |

## Interjection

The VoiceManager can optionally give a "green light to interrupt" to a second voice. This voice is polled by the Interrupt Executor (see §3 in SPEC_2) which decides via structured output whether to interject.
