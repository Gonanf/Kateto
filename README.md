# Kateto — Event-Driven Voice Team for Project Work

![Jane](public/jane1.svg) ![Doktor](public/doktor1.svg) ![Conquest](public/conquest1.svg)

Kateto is an autonomous, event-driven voice team designed for real-time project management and technical collaboration. Instead of forcing conversations through a brittle, linear request-response chain, Kateto runs an event-driven architecture where specialized voice agents, audio hardware, intent classifiers, and autonomous workflows interact concurrently through a centralized `PluginManager` event bus.

---

## 1. Architectural Overview

```
                        +----------------------------------------+
                        |        PluginManager (Event Bus)       |
                        +---+--------+--------+--------+-----+---+
                            |        |        |        |     |
      +---------------------+        |        |        |     +---------------------+
      |                              |        |        |                           |
+-----v-------+               +------v---+  +-v------+ v-------------+     +-------v--------+
| Audio Input |               | Whisper  |  | Intent | | Voice Agent |     | Audio Output   |
| (Mic + VAD) |               | Processor|  | Router | | (LLM + MCP) |     | (TTS + Player) |
+-------------+               +----------+  +--------+ +-------------+     +----------------+
  sounddevice                 whisper.cpp     mmBERT    Jane, Doktor,        Camb AI / Zonos
  Silero VAD                  Vulkan / CUDA  llama.cpp  Conquest             ALSA PCM Mixer
       |                           |             |            |                     |
       v                           v             v            v                     v
 [audio_chunk]             [transcription]   [generate]  [text_chunk]        [audio_output]
                                                                                    |
                                                                                    v
                                                                           +----------------+
                                                                           | Visual Overlay |
                                                                           | (VTuber Avatar |
                                                                           |  + Subtitles)  |
                                                                           +----------------+
```

### The Department & Voice Model

Kateto models organizations as **Departments** populated by domain-specialized **Voices**:
- **Jane (`voice.jane`)** — *Project Coordinator & Orchestrator*. Manages high-level communication, coordinates inter-voice delegation, and interfaces with external stakeholders.
- **Doktor (`voice.doktor`)** — *Technical Planner & Delivery Advisor*. Translates fuzzy requirements into Work Breakdown Structures (WBS), risk matrices, and prioritized backlogs.
- **Conquest (`voice.conquest`)** — *Agile Lead & Scrum Facilitator*. Facilitates standups, sprint retrospectives, process enforcement, and milestone tracking.

---

## 2. Technical Capabilities & Highlights

### ⚡ Hardware-Accelerated Speech-to-Text (Whisper Vulkan / CUDA)
- **Sub-Second Latency**: Transcribes conversational utterances in **~1.5–2.2s** using discrete GPUs (e.g. AMD Radeon RX 6500 XT via Vulkan device 1) instead of 22+ seconds on CPU.
- **Persistent Server Architecture**: Leverages `whisper-server` keeping the quantized model (`ggml-large-v3-turbo-q5_0.bin`) resident in VRAM.
- **Configurable Language**: Supports explicit multilingual target configurations (`audio_processor_whisper.language = "es"`) across HTTP, CLI, and embedded backends.
- **Fault-Tolerant Parsing**: Handles silent VAD frames and background room noise cleanly without throwing validation exceptions.

### 🎙️ Real-Time Token-to-Speech Streaming (Camb AI)
- **Low-Latency Synthesis**: As the LLM generates tokens, `PhraseSegmenter` identifies natural sentence and clause boundaries (configured with punctuation boundaries and token thresholds) and streams them to the TTS engine without waiting for the full response.
- **Streaming Downsampling**: Parses incoming RIFF WAV chunk headers on-the-fly and downsamples 48kHz audio to 24kHz PCM frames directly in memory, yielding audio frames immediately to the output mixer.
- **Glitch-Free ALSA Ring-Buffers**: Eliminates PortAudio ALSA xrun underflows and device contention crashes (`Assertion self->neverDropInput failed`) by maintaining a persistent open output stream with generous buffer sizing (`blocksize=2048`, `latency="high"`).

### 🎭 Visual Overlay & VTuber Avatar Kinematics
- **Audio-Synchronized Subtitles**: Subtitles in the browser overlay are synchronized with **actual audio playback** rather than premature LLM token generation. Subtitles stay on screen for the duration of the spoken sentence plus a 3.5s reading grace period.
- **Reactive Jaw Physics**: Dynamic real-time visemes driven by root-mean-square (RMS) amplitude:
  - Vertical displacement up to **-52px**
  - Random lateral excursions up to **±28px**
  - Rotational tilt up to **±34°** coupled directly to lateral movement direction for lifelike cartoon physics.

### 🧠 LLM KV-Cache Prefilling
- **Zero First-Turn Ingestion Latency**: On runtime startup, Kateto automatically builds each active voice's stable system prompt (personality, tool definitions, durable memories) and dispatches a lightweight 1-token prefill ping with session affinity headers (`x-session-affinity`).
- Inference engines with prefix-caching (such as `llama-server --cache-reuse`, vLLM, or Ollama) ingest and retain the entire prompt prefix in KV memory before the user speaks their first word.

---

## 3. Installation & Dependencies

### Prerequisites
- **Linux** (x86_64) or macOS
- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** package manager
- System libraries for audio: `libportaudio2`, `libasound2`
- For native GPU acceleration: Vulkan drivers (`vulkan-tools`, `mesa-vulkan-drivers`) or NVIDIA CUDA Toolkit

### Setup

```bash
# Clone the repository
git clone https://github.com/Gonanf/Kateto.git
cd Kateto

# Synchronize environment with uv
uv sync

# Optional: Install with in-process backends
uv sync --extra classifier --extra whispercpp

# Or install globally as a standalone CLI tool
uv tool install "kateto[classifier,llamacpp,whispercpp]"
```

---

## 4. Configuration

Bootstrap default configuration files into `~/.config/kateto/`:

```bash
uv run kateto config check
```

Edit `~/.config/kateto/config.toml`:

```toml
[kateto]
name = "Kateto"
language = "es_ar"
log_level = "INFO"

[plugin]
# Microphone Audio Input with Silero VAD
audio_input_mic.enabled = true
audio_input_mic.sample_rate = 16000
audio_input_mic.silence_timeout = 1.0
audio_input_mic.vad_model = "silero"

# Whisper Speech-to-Text Processor
audio_processor_whisper.enabled = true
audio_processor_whisper.backend = "server"
audio_processor_whisper.language = "es"
audio_processor_whisper.model = "/path/to/ggml-large-v3-turbo-q5_0.bin"

# Intent Classification
executor_classifier.enabled = true
executor_classifier.backend = "server"

# Voice LLM Backend (OpenAI-compatible / llama-server / Ollama)
voice_llm.enabled = true
voice_llm.endpoint = "http://127.0.0.1:11434/v1"
voice_llm.model = "qwen2.5-coder:7b"

# Camb AI Streaming TTS
audio_output_camb.enabled = true
audio_output_camb.api_key = "YOUR_CAMB_API_KEY"

# Visual Overlay & HTTP Server
system_http_server.enabled = true
system_http_server.port = 8087
visual_overlay.enabled = true
```

---

## 5. Running the Application

### Start the Runtime

```bash
uv run kateto run
```

This starts:
1. The **Event Bus** and lifecycle manager.
2. Background **LLM system prompt prefill** routines.
3. Microphone listener with **Silero VAD**.
4. The **Vulkan-accelerated Whisper server**.
5. The **FastAPI HTTP & WebSocket server** on `127.0.0.1:8087`.
6. The **Visual Overlay** accessible at [http://127.0.0.1:8087/overlay](http://127.0.0.1:8087/overlay) for OBS browser capture or local viewing.

### Compiling Native Acceleration Backends

Compile native `whisper.cpp` or `llama.cpp` targeting your specific hardware:

```bash
# Vulkan acceleration (AMD / Intel / NVIDIA)
uv run kateto compile whisper --backend vulkan
uv run kateto compile llama --backend vulkan

# NVIDIA CUDA acceleration
uv run kateto compile all --backend cuda

# CPU fallback
uv run kateto compile whisper --backend cpu
```

---

## 6. Testing & Quality Assurance

Kateto enforces strict asynchronous event-safety and zero-regression testing with `pytest-asyncio`:

```bash
# Run the complete test suite
uv run pytest

# Run the bounded end-to-end smoke test
uv run kateto smoke

# Run targeted component suites
uv run pytest kateto/tests/test_whisper_provider.py \
              kateto/tests/test_camb_audio_output.py \
              kateto/tests/test_visual_overlay.py \
              kateto/tests/test_streaming_latency.py
```

---

## 7. Project Journal & Development Tracking

Kateto uses `pj` (Project Journal) to track tasks, features, chores, and bug resolutions:

```bash
# List all tracked project items
./pj list

# Check project health status
./pj status
```

---

## License

Apache 2.0. Developed for the OpenAI Build Week.
