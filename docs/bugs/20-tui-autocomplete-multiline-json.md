---
id: 20
title: "TUI events tab: autocomplete genera JSON multilinea que rompe el Input"
severity: Media
status: resolved
component: kateto/plugins/system/tui.py
resolved: 2026-07-19
---

## 20. TUI events tab: autocomplete genera JSON multilinea que rompe el Input

**Severidad:** Media
**Componente:** `kateto/plugins/system/tui.py`

### Descripción

Al seleccionar un evento registrado vía autocomplete (`/event_name`), `_select_event()` genera un template JSON con `json.dumps(indent=2)` y lo asigna al `Input` widget. `Input` es monolinea — el JSON multilinea rompe la caja de texto (visual corruption, layout roto).

### Impacto

- El input del composer se corrompe visualmente al seleccionar un evento del autocomplete.
- El usuario no puede editar ni enviar el payload.

### Causa

`_json_template()` en `tui.py:777` usaba `json.dumps(fields, indent=2, default=str)`. El resultado multilinea se asignaba a `Input.value`, pero `Input` solo soporta una línea.

### Solución aplicada

Eliminado `indent=2` — el template ahora es JSON compacto en una sola línea.

**Archivo modificado:** `kateto/plugins/system/tui.py` (línea 777)
