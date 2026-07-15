# Voices Overview

Voices are AI agents that inherit from `VoiceAgent(Plugin)`. They are the "people" of Kateto — each with a distinct personality, role, and capabilities.

## Auto-Detection & Instantiation

Voices are auto-detected and instantiated like any other plugin. The PluginManager scans:

| Location | What It Contains |
|---|---|
| `kateto/voices/` | Python subclasses of `VoiceAgent` (code — versioned) |
| `config/kateto/voices/{name}/` | Per-voice data files (SOUL, JOURNAL, MEMORIES — mutable) |

**Discovery flow:**
1. Manager scans `kateto/voices/` for Python files with `VoiceAgent` subclasses
2. For each class, checks `config/kateto/voices/{name}/` for data files (creates defaults if missing)
3. Voice is instantiated with its config section and data directory path
4. Hot-reload works identically to any plugin

**Declarative-only voices** (P1+) don't need a Python subclass — just a data directory with `SOUL.md` is enough for the manager to create a generic `VoiceAgent` instance.

## Processing Mode

Voices are **batch** plugins: they accumulate events in their queue and only generate when they receive a `generate` event. Generation is a streaming async generator.

## Voice Data Files

Each voice has three files in `config/kateto/voices/{name}/`:

| File | Purpose | Size Limit | Mutation |
|---|---|---|---|
| `SOUL.md` | System prompt — personality, role, behavior | 500 words max | Rewritten on 5-min idle timeout |
| `JOURNAL.md` | Stream of consciousness | 50 entries / 3000 tokens sliding window | Append-only |
| `MEMORIES.md` | Long-term recall | 1000 words max | Agent prunes oldest |

## Priority Overview

| Priority | Voices |
|---|---|
| **P0** | Jane, Doktor, Conquest |
| **P1** | Narrador, Susurrante |
| **P2** | Drakula, Xavier, Greedy, Informante, Germ, Business, Lovers |
