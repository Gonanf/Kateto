# Audio Input Plugins

Capture audio from various sources and emit `audio_chunk` events.

## Audio Format

```python
@dataclass
class AudioData:
    samples: bytes          # PCM s16LE
    sample_rate: int = 16000
    channels: int = 1       # Mono
    format: str = "wav"     # In-memory
    source: str = ""
    duration_ms: float = 0.0
```

## Recording Flow

1. Audio input **listens continuously** but only **starts recording when voice activity is detected** (Silero VAD)
2. Records until N seconds of silence (`silence_timeout`)
3. Cuts the audio, packages it as `AudioData`, emits `audio_chunk`
4. **Immediately** resumes listening (async emission means < 50ms gap)
5. Repeats

## Interruption by VAD

When audio input detects voice activity while the system is responding:

1. Emits `interrupt` event to the bus
2. Every plugin listening to `on_interrupt` reacts:
   - **TTS**: stops current playback
   - **LLM Agent**: cancels current generation
   - **Other plugins**: per implementation

## Plugins

### `audio_input_mic` (P0)
Microphone input with Silero VAD.

**Config:**
```toml
[plugin.audio_input_mic]
enabled = true
device = "default"
silence_timeout = 3.0
interrupt_on_vad = true
vad_threshold = 0.5
interrupt_llm = true
interrupt_tts = true
```

**Emits:** `audio_chunk` → `AudioData`, `interrupt`

### `audio_input_meet` (P0)
Google Meet audio capture. Captures meeting audio for processing alongside direct mic input.

**Emits:** `audio_chunk` → `AudioData`, `interrupt`

### `audio_input_desktop` (P2 — Postergated)
Desktop/loopback audio capture. Postergated.

### `audio_input_discord` (P2 — Postergated)
Discord voice channel audio capture. Postergated.

## Multiple Inputs

Multiple audio inputs can be active simultaneously (e.g., mic + desktop). Each emits events independently with its own `source`. Mixing/prioritization happens at the agent level, not the bus level.
