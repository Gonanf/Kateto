---
id: 31
title: "Active workflow is replaced by follow-up input"
severity: Alta
status: resolved
component: kateto/core/workflow_engine.py, kateto/plugins/executor/workflow_router.py, kateto/voices/base.py
resolved: 2026-07-21
---

## 31. Active workflow is replaced by follow-up input

**Severidad:** Alta
**Componente:** `kateto/core/workflow_engine.py`, `kateto/plugins/executor/workflow_router.py`

### Descripción

After a workflow started, a follow-up answer could be classified as a different
workflow and the active conversation lost its workflow context.

### Impacto

The agent could abandon the current phase before asking its required questions,
using tools, or producing the phase deliverables.

### Causa

The workflow engine only rejected duplicate executions of the same workflow and
voice pair. It did not reserve a voice while another workflow was running, and
interrupt events also marked active workflows as stopped.

### Solución aplicada

The engine now exposes active runs and refuses a second workflow for an occupied
voice. The router sends follow-up input as a contextual `voice_request` to the
active workflow owner without invoking workflow selection. Interrupts cancel
generation but preserve workflow state. Voice requests include an internal system
instruction that directs the agent to ask the phase questions, use tools, and stay
in the workflow until completion or an explicit stop.

**Archivos:** `kateto/core/event.py`, `kateto/core/workflow_engine.py`,
`kateto/plugins/executor/workflow_router.py`, `kateto/voices/base.py`
