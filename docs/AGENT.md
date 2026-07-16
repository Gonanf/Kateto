# AGENT — Full Specification

This directory documents the **complete Kateto specification** as defined in `SPEC.md`.

`SPEC.md` is the canonical MVP reference; there is no separate `MVP.md`. These docs cover the broader architecture — MVP/P0 plus post-MVP P1, P2, and P3 material — and explicitly mark features that are outside the shipped MVP.

## What's Different From the MVP

| Feature | MVP | Full Spec |
|---|---|---|
| Voices | Jane, Doktor, Conquest (P0) | + Narrador, Susurrante (P1), Drakula, Xavier, Greedy, Informante, Germ, Business, Lovers (P2) |
| VoiceClassifier | Not implemented (P1) | Per-voice routing via fine-tuned mmBERT |
| Executors | Classifier, Interrupt, TODO List | + RandomTalk, Podcast (P2) |
| Workflow phases | Declarative only | Declarative + Imperative (shell scripts, templates) |
| MCP per voice | Config-declared servers with explicit per-voice grants; deny by default | Broader per-voice MCP server configuration |
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
| **P1** | Post-MVP, not part of the shipped MVP |
| **P2** | Nice to have |
| **P3** | Future / excluded from v1 |
