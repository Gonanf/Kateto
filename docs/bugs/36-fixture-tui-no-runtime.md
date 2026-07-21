---
id: 36
title: Fixture TUI starts without responses or workflows
severity: Alta
status: resolved
component: kateto/plugins/system/tui.py
resolved: 2026-07-21
---

## 36. Fixture TUI starts without responses or workflows

**Severidad:** Alta
**Componente:** kateto/plugins/system/tui.py

### Descripción

The fixture TUI rendered its shell but did not run a model-like response path or expose the default workflow catalog.

### Impacto

Fixture mode could not demonstrate the event bus, voice coordination, generated responses, or workflow state without external providers.

### Causa

The fixture runtime enabled inert placeholder plugins named after voices and the workflow engine. It never enabled WorkflowEngine or VoiceAgent instances, and it did not bootstrap default workflows for a fresh fixture configuration directory.

### Solución aplicada

The fixture runtime now bootstraps defaults, enables the real WorkflowEngine, enables three deterministic VoiceAgent instances, starts project-initiation as a visible demonstration, and tests the runtime event path plus rendered workflow tree and conversation.

### Archivos

kateto/plugins/system/tui.py, kateto/tests/test_tui.py
