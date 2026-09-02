---
id: 72
title: "Decoupled voice folder configuration and dynamic plugin parameter registry"
severity: Media
status: resolved
component: kateto/core/config.py
resolved: 2026-08-31
---

## 72. Decoupled voice folder configuration and dynamic plugin parameter registry

**Severidad:** Media  
**Componente:** [`kateto/core/config.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/core/config.py), [`kateto/plugins/audio_output/boson_tts_plugin.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/audio_output/boson_tts_plugin.py), [`kateto/voices/prompt_blocks.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/voices/prompt_blocks.py)

### Descripción

1. Previously, voice settings were only configurable via the central `config.toml` file under `[voice.<name>]`, preventing voice directories (`~/.config/kateto/voices/<name>/`) from self-contained configuration of their own plugin instances (TTS provider, voice ID, skills, etc.).
2. Every plugin-specific parameter (such as `camb_voice_id`, `edge_tts_voice`, `boson_voice`, etc.) had to be hardcoded as explicit fields on `VoiceSettings` or `PluginSettings` due to `extra="forbid"`, which broke modularity whenever new plugins introduced custom parameters.
3. Boson AI Higgs TTS 3 lacked support for inline control tokens (emotion, style, SFX, and prosody) in voice agent system prompt instructions.

### Impacto

- Adding new plugins required altering core configuration classes.
- Voice folders could not declare their own configuration independently.
- Voice agents could not utilize expressive speech capabilities available in Boson Higgs-TTS 3.

### Causa

- `_ConfigModel` inherited directly from `EventModel` with `ConfigDict(extra="forbid", strict=True, frozen=True)`.
- Voice loader did not scan `config_dir / "voices" / <name> / "config.toml"`.

### Solución aplicada

1. Introduced `_ExtensibleConfigModel` (`extra="allow"`, dynamic `.get(key, default)` and `__getattr__` resolution) for `PluginSettings` and `VoiceSettings`.
2. Created `PluginConfigRegistry` allowing plugins to declare custom settings on their own sections (`register_plugin_param`) and on voice instances (`register_voice_param`).
3. Added `_load_voice_folder_configs()` in `kateto/core/config.py` to automatically load and merge `voices/<name>/config.toml` directly into voice settings.
4. Created default `config.toml` in all voice directories (`jane`, `doktor`, `conquest`, `whisperer`).
5. Implemented `BosonAudioOutput` plugin in [`kateto/plugins/audio_output/boson_tts_plugin.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/audio_output/boson_tts_plugin.py) emitting PCM chunks to the manager and handling interruptions.
6. Expanded `_boson_prompt_block()` in [`kateto/voices/prompt_blocks.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/voices/prompt_blocks.py) with comprehensive guidance on Higgs TTS 3 tags (`<|emotion:...|>`, `<|style:...|>`, `<|sfx:...|>`, `<|prosody:...|>`).

**Archivos:** `kateto/core/config.py`, `kateto/core/plugin.py`, `kateto/plugins/audio_output/boson_tts_plugin.py`, `kateto/plugins/audio_output/__init__.py`, `kateto/voices/prompt_blocks.py`, `kateto/voices/base.py`, `kateto/tests/test_boson_tts.py`
