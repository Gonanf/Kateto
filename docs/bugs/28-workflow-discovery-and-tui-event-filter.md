---
id: 28
title: "Workflow startup fallback and TUI event stream filtering"
severity: Alta
status: resolved
component: kateto/plugins/executor/classifier.py, kateto/plugins/system/tui.py
resolved: 2026-07-21
---

## 28. Workflow startup fallback and TUI event stream filtering

**Severidad:** Alta  
**Componente:** `kateto/plugins/executor/classifier.py`, `kateto/plugins/system/tui.py`

### Descripción

New-project requests could reach the classifier without a selected workflow, and the TUI omitted `text_chunk` and `audio_output` events from its event stream.

### Impacto

Jane did not reliably start `project-initiation`, and the TUI did not show every event sent through the runtime.

### Causa

Workflow names were available to the classifier but no deterministic project-initiation fallback existed. The TUI had an explicit noisy-event filter.

### Solución aplicada

New-project intent now resolves to the discovered `project-initiation` workflow for Jane when the classifier omits a workflow. Voice prompts include each voice's workflow catalog and the `workflow_run` event mechanism. The TUI observer now records and renders all observed events.

**Archivos:** `kateto/plugins/executor/classifier.py`, `kateto/voices/base.py`, `kateto/plugins/system/tui.py`
