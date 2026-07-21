---
id: 29
title: "Workflow starts without sending phase instructions to a voice"
severity: Alta
status: resolved
component: kateto/core/workflow_engine.py
resolved: 2026-07-21
---

## 29. Workflow starts without sending phase instructions to a voice

**Severidad:** Alta
**Componente:** `kateto/core/workflow_engine.py`

### Descripción

The workflow engine emitted `workflow_started` and `workflow_phase_start`, but a phase
with no explicit called voice did not emit a `voice_request` for the workflow owner.

### Impacto

The workflow appeared active in the TUI but no `generate` event reached an LLM voice,
so the workflow performed no model work.

### Causa

Phase dispatch considered only `calls_voices`; it omitted the voice that owns the
workflow run.

### Solución aplicada

Each phase now requests the owning voice first, followed by its declared called voices,
with case-insensitive deduplication. The owner receives the phase instructions and can
emit the normal `generate` event through the event bus.

**Archivos:** `kateto/core/workflow_engine.py`, `kateto/tests/test_workflow_router.py`
