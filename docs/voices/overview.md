# Voices Overview

Voices are AI agents created from configuration + data. They are the "people" of Kateto — each with a distinct personality, role, and capabilities.

## Factory-Based Discovery

Voices are created by `kateto/voices/factory.py` using `VoiceProfile` dicts from the `_PROFILES` registry. No Python subclass scanning.

| Location | What It Contains |
|---|---|
| `kateto/voices/factory.py` | `VoiceProfile` definitions and `create_voice()` factory |
| `~/.config/kateto/voices/{name}/` | Per-voice data files (SOUL, JOURNAL, MEMORIES — mutable) |

**Discovery flow:**
1. `create_voice(name)` looks up `VoiceProfile` in `_PROFILES` dict
2. Profile provides: `voice_id`, `display_name`, `role`, `system_prompt`
3. `VoiceAgent` is instantiated with profile + `VoiceMemory` for data storage
4. Optional: `VoiceToolExecutor` + `KatetoToolset` for pydantic-ai tool-calling

**Adding a new voice:**
1. Add `VoiceProfile` entry to `_PROFILES` in `factory.py`
2. Create config section `[voice.<name>]` in `config.toml`
3. Create `~/.config/kateto/voices/<name>/SOUL.md`

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
