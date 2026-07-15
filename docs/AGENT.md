# AGENT — Full Specification

This directory documents the **complete Kateto specification** as defined in `SPEC.md`.

**This is NOT the MVP.** The MVP (`MVP.md`) is a slimmed-down P0 vertical slice for Build Week delivery. These docs cover the full architecture — P0, P1, P2, and P3 — including features explicitly excluded from the MVP.

## What's Different From the MVP

| Feature | MVP | Full Spec |
|---|---|---|
| Voices | Jane, Doktor, Conquest (P0) | + Narrador, Susurrante (P1), Drakula, Xavier, Greedy, Informante, Germ, Business, Lovers (P2) |
| VoiceClassifier | Not implemented (P1) | Per-voice routing via fine-tuned mmBERT |
| Executors | Classifier, Interrupt, TODO List | + RandomTalk, Podcast (P2) |
| Workflow phases | Declarative only | Declarative + Imperative (shell scripts, templates) |
| MCP per voice | Global MCP only | Per-voice MCP server config + Skills system |
| Connectors | Calendar, Meet, CLI | + Discord, OpenProject (P2) |
| Workspaces | Not implemented (P3) | Isolated contexts per project/person |
| Avatars | Not implemented (P3) | Puppet-mask SVG avatars + video overlay |
| VideoRAG | Not implemented (P3) | Vision processing for video input |
| Remotion | Not implemented (P3) | Tutorial video runner |

## Document Structure

```
docs/
├── AGENT.md                 # This file
├── architecture/
│   ├── overview.md          # System overview & principles
│   ├── event-system.md      # Event contracts, dispatch, lifecycle
│   ├── plugin-manager.md    # Singleton, lifecycle, API
│   ├── hot-reload.md        # Watchdog, graceful reload
│   └── config.md            # TOML, secrets, env
├── plugins/
│   ├── audio-input.md       # Mic, Meet, desktop, Discord
│   ├── audio-processor.md   # Whisper, QwenASR, diarization
│   ├── audio-output.md      # Zonos, QwenTTS, llama.cpp TTS
│   ├── executors.md         # Classifier, Interrupt, VoiceClassifier, TODO, RandomTalk, Podcast
│   ├── connectors.md        # Calendar, Meet, CLI, Discord, OpenProject
│   └── system.md            # TUI, MCP Server
├── voices/
│   ├── overview.md          # VoiceAgent architecture, auto-detection
│   ├── voice-agent.md       # Base class, generation, queue
│   ├── voice-list.md        # All 12 voices with personalities
│   ├── workflows.md         # Declarative + imperative phases
│   ├── backlog.md           # Product backlog, sprint management
│   ├── skills-and-mcp.md    # Per-voice MCP servers & skills
│   └── voice-evolution.md   # SOUL, JOURNAL, MEMORIES lifecycle
├── concepts/
│   ├── workspaces.md        # Context isolation (P3)
│   └── avatars.md           # Puppet-mask visual design (P3)
└── development/
    ├── tooling.md           # uv, dependencies, project setup
    ├── tdd.md               # RED→GREEN→REFACTOR, testing strategy
    ├── project-structure.md # Full directory tree
    └── build-week.md        # Delivery requirements, demo strategy
```

## Development Status Legend

| Badge | Meaning |
|---|---|
| **P0** | MVP — implemented during Build Week |
| **P1** | Post-MVP, high priority |
| **P2** | Nice to have |
| **P3** | Future / excluded from v1 |
