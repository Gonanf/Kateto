# SPEC_2 — Implementation Plan (Deferred)

**Source:** [SPEC_2.md](../../SPEC_2.md) — Data/control plane split, VoiceManager orchestration, audio pipeline.

## Changes Reverted

These were partially implemented then reverted. Documented here for clean implementation after codebase simplification.

---

## 1. `capabilities` field on VoiceProfile

**Files:** `kateto/voices/base.py`, `kateto/voices/factory.py`

Add `capabilities: tuple[str, ...] = ()` to `VoiceProfile` dataclass. Set per-voice in `factory.py`:

| Voice | capabilities |
|-------|-------------|
| jane | `("orchestration", "coordination", "general")` |
| doktor | `("planning", "backlog", "risk")` |
| conquest | `("agile", "ceremonies", "process")` |

**Why:** VoiceManager needs to know what each voice can do for capability-matched routing.

---

## 2. New Event Models

**File:** `kateto/core/event.py`

Add three event models:

```python
class SpeakRequestData(EventModel):
    voice: str
    prompt: str
    workflow: str | None = None
    phase_id: str | None = None

class SpeakingStateData(EventModel):
    voice: str
    active: bool

class InterjectData(EventModel):
    voice: str
    prompt: str
```

Also re-export `GenerateData` if not already exposed.

---

## 3. AudioPipeline Dataclass

**File:** `kateto/voices/base.py`

```python
@dataclass
class AudioPipeline:
    token_queue: asyncio.Queue[str | None]
    pcm_queue: asyncio.Queue[bytes | None]
```

Add `_pipeline: AudioPipeline | None = None` to `VoiceAgent.__init__`.

In `_stream_response` and `_agent_loop`: push tokens to `pipeline.token_queue`, push `None` sentinel on completion.

Add `on_speak` handler and `_do_generate` helper to VoiceAgent. Register `speak` event in `initialize()`.

---

## 4. VoiceManager Plugin

**File:** `kateto/plugins/system/voice_manager.py` (new)

Plugin that:

- Handles `generate` events (from classifier EXECUTE) → picks a voice via weighted random
- Handles `voice_enable` events (from TUI) → enables/disables voice plugins
- `_eligible_voices(prompt)`: filters by `"voice"` capability + relevance terms
- `_pick_voice(eligible)`: weighted random from `_DEFAULT_PROBABILITIES` (`jane=0.7, doktor=0.15, conquest=0.1, whisperer=0.05`)
- Handles `speaking_state` events to track current speaker

**Registration events:** `generate`, `speak`, `voice_enable`, `voice_enabled`, `speaking_state`, `interject`.

---

## 5. Classifier Route Change

**File:** `kateto/plugins/executor/classifier.py`

Change the EXECUTE → generate emit to target `"voice_manager"` instead of individual voices:

```python
target="voice_manager",
```

---

## 6. TTS/Player Pipeline Support

**Files:**
- `kateto/plugins/audio_output/zonos.py`
- `kateto/plugins/audio_output/camb.py`
- `kateto/plugins/audio_output/edgetts.py`
- `kateto/plugins/audio_output/player.py`

Each TTS plugin gets:
- Import `AudioPipeline` from `kateto.voices.base`
- `_pipeline: AudioPipeline | None = None` in `__init__`
- `_pipeline_task: asyncio.Task | None = None` in `__init__`
- Pipeline startup in `enable()`: create task for `_run_pipeline()`
- Pipeline shutdown in `disable()`: cancel task
- Guard in `on_text_chunk()`: `if self._pipeline is not None: return`
- `_run_pipeline()`: reads tokens from `pipeline.token_queue`, generates PCM via provider, pushes to `pipeline.pcm_queue`

Player gets:
- Same import + attributes + enable/disable
- Guard in `on_audio_output()`: `if self._pipeline is not None: return`
- `_run_pipeline()`: reads PCM from `pipeline.pcm_queue`, writes to audio device stream

Sentinel protocol: `None` on token_queue = end of generation; `None` on pcm_queue = end of playback.

---

## 7. Wire VoiceManager into Runtime

**File:** `kateto/run_mode.py`

- Remove old `_VoiceManagerPlugin` class
- Remove `RuntimeOwner.on_voice_enable` method
- Remove unused imports (`VoiceEnableData`, `VoiceEnabledData`, `DiscoveryContext`)
- Import `VoiceManager` from `kateto.plugins.system.voice_manager`
- In `start()`: replace `_VoiceManagerPlugin(self)` with `VoiceManager(self._config)`

---

## 8. Config Changes

**File:** `kateto/core/config.py`

Add to `PluginSettings`:

```python
voice_probabilities: dict[str, float] | None = None
```

**File:** `config/defaults/config.toml`

Add section:

```toml
[plugin.voice_manager]
voice_probabilities = { jane = 0.7, doktor = 0.15, conquest = 0.1, whisperer = 0.05 }
```
