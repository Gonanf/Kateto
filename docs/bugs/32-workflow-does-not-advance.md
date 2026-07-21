---
id: 32
title: "Workflow agent does not complete phases or deliverables"
severity: Alta
status: resolved
component: kateto/voices/base.py, kateto/voices/tools.py
resolved: 2026-07-21
---

## 32. Workflow agent does not complete phases or deliverables

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`, `kateto/voices/tools.py`

### Descripción

The voice could receive workflow instructions and answer conversationally, but it
did not receive the concrete phase completion contract needed to produce the
workflow events that advance tasks and deliverables.

### Impacto

Workflows remained in their initial phase and did not publish completion or move
to the next phase.

### Causa

The system prompt omitted phase deliverables and checkpoints. In addition, the
generated schema described the list fields of `workflow_phase_complete` as
objects, which made the tool ambiguous or invalid for the model.

### Solución aplicada

The voice system context now includes phase tasks, deliverables, checkpoints, and
the exact instruction to dispatch `workflow_phase_complete`. Event-tool schemas
now represent list fields as arrays with object items.

**Archivos:** `kateto/voices/base.py`, `kateto/voices/tools.py`,
`kateto/tests/test_voice_history.py`
