---
id: 87
title: "Voice generate fails with ReferenceClipError when TTS provider is not Zonos"
severity: Alta
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-06
---

## 87. Voice generate fails with ReferenceClipError when TTS provider is not Zonos

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`, `kateto/providers/__init__.py`

### Descripción

When a voice uses a non-Zonos TTS provider (e.g., `edge_tts`), calling `generate` or `speak` raises `ReferenceClipError` because `VoiceAgent.reference_wav` is eagerly resolved in `_stream_response` — even though no TTS provider that needs a reference WAV is active. The `reference_wav` field in `GenerationRequest` was a required `Path`, and the property unconditionally validates that the file exists on disk.

### Impacto

Any voice configured with `tts_provider = "edge_tts"` (or `"camb"`, `"boson"`) crashes on every text generation attempt. The error is raised before the LLM provider is even contacted, so the voice produces no output at all. This affects the bate_debate orchestrator, the CLI `debate` command, and any live voice interaction.

### Causa

1. `GenerationRequest.reference_wav` was typed as `Path` (non-optional), forcing every call site to provide a valid WAV path.
2. `_stream_response` unconditionally accessed `self.reference_wav` (a property that validates file existence) regardless of which TTS provider was configured.
3. No LLM provider (`OpenAICompatibleProvider`, `RWKVROCmProvider`) actually consumes `request.reference_wav` — it is only relevant for Zonos voice cloning.

### Solución aplicada

1. Changed `GenerationRequest.reference_wav` from `Path` to `Path | None` so providers that don't need a reference WAV can omit it.
2. In `_stream_response`, only resolve `self.reference_wav` when `self._settings.tts_provider == "zonos"`. For all other providers, pass `None`.
3. Updated `gen_discussion.py` to pass `reference_wav=None` (it creates `GenerationRequest` directly for `OpenAICompatibleProvider`, which never uses the field).

### Archivos

`kateto/voices/base.py`, `gen_discussion.py`, `docs/src/content/docs/bugs/known-issues.md`, `docs/src/content/docs/bugs/87-reference-wav-validation-blocks-non-zonos-tts.md`
