---
id: 55
title: "DiskMediaStore object is not callable in VoiceAgent capabilities"
severity: Alta
status: resolved
resolved: 2026-08-09
component: kateto/voices/factory.py
---

## 55. DiskMediaStore object is not callable in VoiceAgent capabilities

**Severidad:** Alta
**Componente:** `kateto/voices/factory.py`

### Descripción

When creating a voice agent via `create_voice()`, `_capabilities_for()` attempts to append `DiskMediaStore` directly to the agent's `capabilities` list. Because `DiskMediaStore` is a storage class (`MediaStore`) and not a `pydantic_ai` `Capability` object, `pydantic_ai` raises a `TypeError: 'DiskMediaStore' object is not callable` during speech generation (`speak` / `generate`).

### Impacto

Voice speech generation (`speak` event) fails with a `TypeError` whenever `pydantic_ai_harness` is installed and `DiskMediaStore` gets included in agent capabilities.

### Causa

`DiskMediaStore` is a media storage engine for offloading large binary content in step persistence, not an agent capability. Appending it to `capabilities` violates the `Capability` interface expected by `pydantic_ai`.

**Solución aplicada:**
Removed `capabilities.append(DiskMediaStore(directory=voice_dir / "media"))` from `_capabilities_for()` in `kateto/voices/factory.py`.

**Archivos:** `kateto/voices/factory.py`
