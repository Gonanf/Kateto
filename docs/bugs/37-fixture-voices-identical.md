---
id: 37
title: Fixture voices use identical response behavior
severity: Media
status: resolved
component: kateto/plugins/system/tui.py
resolved: 2026-07-21
---

## 37. Fixture voices use identical response behavior

**Severidad:** Media
**Componente:** kateto/plugins/system/tui.py

### Descripción

The fixture TUI produced a response from every voice, but the response behavior differed only by the speaker name.

### Impacto

The fixture did not demonstrate the distinct orchestration, delivery, and agile roles that are central to Kateto's team model.

### Causa

The deterministic provider used one shared response template for all fixture voices.

### Solución aplicada

The fixture provider now receives a role-specific response instruction: Jane coordinates, Doktor focuses on delivery and backlog risks, and Conquest facilitates the agile process. Regression tests assert all three role signals.

### Archivos

kateto/plugins/system/tui.py, kateto/tests/test_tui.py
