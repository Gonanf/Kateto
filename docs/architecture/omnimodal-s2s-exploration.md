# Omnimodal Speech-to-Speech (S2S) Exploration for Kateto

## Executive Summary

Kateto's current architecture relies on a **decoupled, multi-hop pipeline**:
1. **Audio Input**: Mic capture & Silero VAD (`audio_input`)
2. **ASR**: Whisper via `whisper.cpp` (`audio_processor`)
3. **Intent Classification**: mmBERT/LLM classifier (`executor/classifier.py`)
4. **LLM Orchestration**: `llama.cpp` / OpenAI provider with Pydantic-AI tool calling (`voices/`)
5. **TTS Synthesis**: Zonos / EdgeTTS (`audio_output`)

While modular, this multi-hop pipeline introduces latency (~800ms – 1.4s overall turn latency) and separates phonetic/tonal context from semantic understanding.

Emerging **omnimodal models** (`MiniCPM-o 4.5 GGUF`, `Qwen3-Omni-30B-A3B GGUF`) and streaming frameworks ([`huggingface/speech-to-speech`](https://github.com/huggingface/speech-to-speech)) merge ASR, intent classification, LLM reasoning, and TTS into a unified streaming model or end-to-end full-duplex speech loop.

---

## Model & Framework Comparison

| Dimension | Current Kateto Stack | MiniCPM-o 4.5 (GGUF) | Qwen3-Omni-30B-A3B (GGUF) | HF `speech-to-speech` / FastRTC |
|---|---|---|---|---|
| **Architecture** | Decoupled (Whisper + LLM + Zonos) | Unified End-to-End Omni-Flow (9B) | MoE Thinker-Talker (30B Total / 3B Active) | Modular Pipeline Wrapper / WebRTC Server |
| **Input / Output** | PCM → Text → Text → PCM | Audio + Vision → Audio + Text | Audio + Vision + Text → Audio + Text | WebRTC / WebSocket Audio Stream |
| **Inference Latency** | ~800ms - 1400ms total | ~150ms - 300ms (Full Duplex) | ~200ms - 450ms (MoE streaming) | Depends on backend (OpenAI Realtime API wrapper) |
| **VRAM Footprint** | ~6-10 GB (combined servers) | ~8-12 GB (Q4_K_M) | ~16-22 GB (Q4_K_M) | Variable (Proxies to local or remote endpoints) |
| **Full-Duplex Interruption** | Handled via Silero VAD + Event Bus | Native (Omni-Flow temporal alignment) | Native turn-taking & talker head | Built-in FastRTC VAD & interruption buffer |
| **Tool Calling / MCP** | Full Pydantic-AI & MCP support | Text output channel supports JSON/Tools | Strong instruction-following & tool calls | OpenAI Realtime API format (`response.function_call_arguments.delta`) |
| **Kateto Compatibility** | Native | Requires GGUF speech token decoder server | Requires `llama.cpp` MoE + audio mmproj server | **Direct fit** (Exposes OpenAI Realtime WebRTC endpoint) |

---

## Detailed Model Breakdown

### 1. `openbmb/MiniCPM-o-4_5-gguf`
* **Core Strengths**: 9B parameter omnimodal model built for real-time full-duplex multimodal live streaming. It sees, listens, and speaks concurrently without blocking input streams.
* **Audio-to-Audio Tokens**: Uses an integrated audio tokenizer (DAC/Vector-Quantized codec) allowing direct speech generation.
* **GGUF / `llama.cpp` Status**: GGUF weights exist. Full audio-in/audio-out token decoding in vanilla `llama.cpp` requires the `llama-omni` extension or specialized audio decoder head bindings.
* **Fit for Kateto**: Exceptional for single-agent low-latency voice interaction, though multi-persona voice cloning requires injecting audio reference vectors into the server prompt.

### 2. `ggml-org/Qwen3-Omni-30B-A3B-Instruct-GGUF`
* **Core Strengths**: Mixture-of-Experts (MoE) model (30B total, 3B active parameters per token). Highly performant, superior reasoning and multilingual comprehension.
* **Omnimodal Processing**: Processes audio features directly via an audio projector (`--mmproj` GGUF feature map).
* **GGUF / `llama.cpp` Status**: Supported in `llama.cpp` for text/audio input. Audio output generation relies on SNAC or CosyVoice codebook token synthesis.
* **Fit for Kateto**: Ideal for complex project work (Doktor planning, Conquest agile ceremonies) where high reasoning capacity and tool execution are needed concurrently with voice output.

### 3. `huggingface/speech-to-speech` & FastRTC
* **Core Strengths**: Provides an OpenAI Realtime API compatible WebRTC server framework. Handles VAD, WebRTC handshakes, turn-taking, and streaming transport.
* **Server Architecture**: Can act as a gateway that connects local whisper.cpp + llama.cpp + TTS OR native omnimodal models to WebRTC clients.
* **Fit for Kateto**: **Highest immediate architectural value**. Kateto can run a `speech-to-speech` WebRTC plugin or client adapter that connects Kateto's `PluginManager` directly to an OpenAI Realtime compatible endpoint.

---

## Architectural Alignment with Kateto Principles

Kateto's Core Architecture Principle #4 states:
> **External Inference First**: AI models run as local HTTP/gRPC/WebRTC servers. The Python process never loads heavy ML PyTorch models directly into process memory.

### Integration Strategy: The `OmnimodalConnectorPlugin`

Instead of replacing Kateto's event bus, an omnimodal model fits into Kateto as an **external engine plugin**:

```
                                 ┌─────────────────────────────────────────────────────────┐
                                 │                 External Inference Server               │
                                 │  (MiniCPM-o / Qwen3-Omni / speech-to-speech WebRTC)    │
                                 └───────────────────────────┬─────────────────────────────┘
                                                             │
                                                  WebRTC / WebSocket Stream
                                                             │
                                                             ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ KATETO CORE EVENT BUS (PluginManager)                                                                 │
 │                                                                                                        │
 │   [AudioInput Plugin] ─────(AudioData)────► [OmnimodalConnectorPlugin] ────(AudioOutput)──► [Speaker]  │
 │                                                   │              │                                     │
 │                                            (TranscriptionData) (TextChunk)                             │
 │                                                   │              │                                     │
 │                                                   ▼              ▼                                     │
 │                                            [VoiceManager]  [TUI / Memory]                              │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Event Flow with Omnimodal Engine:
1. **Audio Streaming**: `AudioInput` records mic audio and sends `AudioData` chunks via WebSocket/WebRTC to the Omnimodal Server.
2. **Native Perception**: The Omnimodal model evaluates intent, tone, and self-talk natively in real time (reducing the need for a separate `classifier.py` step).
3. **Dual Stream Emission**:
   - **Audio Stream**: Raw PCM audio output streams directly to `AudioOutput` (or low-latency playback buffer).
   - **Control/Text Stream**: Transcribed user text (`TranscriptionData`), assistant responses (`TextChunk`), and requested tool calls (`ToolCallData`) are emitted onto the `PluginManager` bus.
4. **Tool Execution Loop**: If the model requests an MCP tool execution, Kateto's `VoiceToolExecutor` runs the tool asynchronously and sends the result back to the server.

---

## Next Steps & Recommendations

1. **Phase 1: Proof of Concept Plugin**: Create `kateto/plugins/audio_processor/omnimodal_connector.py` implementing an OpenAI Realtime WebRTC / WebSocket protocol adapter.
2. **Phase 2: Benchmark Latency**: Test `MiniCPM-o 4.5 GGUF` vs `Qwen3-Omni 30B GGUF` vs standard Kateto pipeline using `--fixture` and local GGUF servers.
3. **Phase 3: Multi-Voice Orchestration**: Map Kateto's voice profiles (Jane, Doktor, Conquest) to audio prompt speaker embeddings or system instructions in the omnimodal server.
