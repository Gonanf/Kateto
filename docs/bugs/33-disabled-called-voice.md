---
id: 33
title: "Workflow calls a disabled voice without activating it"
severity: Alta
status: resolved
component: kateto/core/workflow_engine.py, kateto/run_mode.py
resolved: 2026-07-21
---

## 33. Workflow calls a disabled voice without activating it

**Severidad:** Alta
**Componente:** `kateto/core/workflow_engine.py`, `kateto/run_mode.py`

### Descripción

A workflow phase could list another voice in `calls_voices` while that voice was
disabled. The engine looked only for an already active plugin and discarded the
request when it was not found.

### Impacto

Cross-voice orchestration silently skipped the specialist voice and its work.

### Causa

There was no lifecycle handshake between the workflow engine and the runtime voice
manager before emitting the targeted `voice_request`.

### Solución aplicada

The engine now emits `voice_enable` and stores the pending request. The runtime
voice manager activates the configured voice, emits `voice_enabled`, and the engine
then sends the pending request to the newly registered voice. Configuration lookup
is case-insensitive so workflow display names such as `Doktor` resolve to config
keys such as `doktor`.

**Archivos:** `kateto/core/event.py`, `kateto/core/workflow_engine.py`,
`kateto/run_mode.py`, `kateto/tests/test_event_routing.py`
