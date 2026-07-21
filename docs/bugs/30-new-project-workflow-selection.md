---
id: 30
title: "New project requests select an unrelated workflow"
severity: Alta
status: resolved
component: kateto/plugins/executor/workflow_router.py
resolved: 2026-07-21
---

## 30. New project requests select an unrelated workflow

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/workflow_router.py`

### Descripción

The dynamic semantic selector could choose `stakeholder-communication` for an explicit
new-project request instead of the project initiation workflow.

### Impacto

Project setup skipped the intended requirements and initiation steps.

### Causa

All available workflows were sent to semantic selection without preserving the existing
new-project invariant.

### Solución aplicada

New-project phrases, including Spanish `nuevo proyecto`, now prefer the available
`project-initiation` workflow. Other requests continue through dynamic mmBERT selection.

**Archivos:** `kateto/plugins/executor/workflow_router.py`, `kateto/tests/test_workflow_router.py`
