# System Overview

**Kateto** is an intelligent event bus where audio plugins, AI agents (Voices), and external services communicate in a decentralized manner. Its core is a **PluginManager** broker that handles both plugin lifecycle and event routing — there is no separate mediator component.

## Design Principles

### 1. Conversational
Latency matters more than anything. The system must respond as fast as a human conversation. This drives:
- Shortest possible pipelines
- Streaming mandatory in every response path
- Minimum overhead per event hop
- No blocking waits
- Local processing over remote whenever viable

### 2. Usable
The system must do real work faster than doing it manually. Not a tech demo — it integrates with real tools (Calendar, terminal, GitHub, Taskwarrior), creates concrete artifacts (tasks, reports, TODO.md), and demonstrates that voice-driven project management is genuinely faster than clicking through Jira.

### 3. Streaming First
Audio, LLM tokens, and TTS all stream. Everything possible should be in stream mode. Non-streaming is only for edge cases.

### 4. External Inference First
AI models run as local HTTP servers:
- Whisper (whisper.cpp)
- LLM (llama.cpp — OpenAI-compatible API)
- mmBERT classifier (GGUF via llama.cpp)
- Zonos TTS (zonos2.cpp)

The Python process never loads ML models directly. Bring Your Own: the user chooses the model, inference platform, and server.

### 5. Broker Architecture
No central mediator. All plugins communicate independently through the event bus. The PluginManager is the bus — not a separate component.

### 6. TDD
RED → GREEN → REFACTOR is mandatory for all development.

## High-Level Flow

```
User speaks → AudioInput records → emits audio_chunk
  → AudioProcessor transcribes → emits transcription
  → Classifier classifies intent
    → On EXECUTE: emits generate for matching voices
  → VoiceAgent generates response (streaming tokens)
    → Tokens stream to TTS → audio output
    → Tokens also emitted as event for other voices
  → User interrupts → AudioInput emits interrupt
    → TTS stops, LLM cancelled, loop restarts
```

## Priority Overview

| Priority | Components |
|---|---|
| **P0** | Event Bus, PluginManager, Audio Input (Mic), Whisper, Zonos TTS, Classifier, Interrupt, Jane, Doktor, Conquest, TUI, MCP Server, Google Meet, Calendar |
| **P1** | Narrador, Susurrante, VoiceClassifier, TODO List Executor, CLI Connector |
| **P2** | Drakula, Xavier, Greedy, Informante, Germ, Business, Lovers, Discord, OpenProject, RandomTalk, Podcast, Avatars |
| **P3** | Workspaces, VideoRAG, Remotion Tutorial Runner |
