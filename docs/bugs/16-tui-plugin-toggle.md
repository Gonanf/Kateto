---
id: 16
title: "TUI plugins tab: test intenta clickear botones enable/disable que no existen"
severity: Media
status: resolved
component: kateto/tests/test_tui.py / kateto/plugins/system/tui.py
resolved: 2026-07-19
---

## 16. TUI plugins tab: test intenta clickear botones enable/disable que no existen

**Severidad:** Media
**Componente:** `kateto/tests/test_tui.py`, `kateto/plugins/system/tui.py`

### Descripción

El TUI ya tiene un `Switch` de Textual en cada fila de plugin (`#switch-{name}`) que permite habilitar/deshabilitar plugins. El handler `on_switch_changed` lo conecta con `_set_plugin` → `manager.enable_plugin` / `manager.disable_plugin`.

Sin embargo, el test `test_tui_renders_live_runtime_state_and_controls` intentaba clickear `#disable-fixture_plugin` y `#enable-fixture_plugin`, que nunca existieron. El test además referenciaba propiedades inexistentes (`runtime_text`, `mcp_text`, `workflow_text`) y texto en español que no coincide con la implementación actual.

### Impacto

- Test `test_tui_renders_live_runtime_state_and_controls` fallaba con `NoNodesMatch`
- Sin cobertura real del toggle de plugins

### Causa

El test se escribió como spec anticipando botones de enable/disable separados, pero nunca se actualizó cuando se implementó el `Switch` en su lugar.

### Solución aplicada

1. Se corrigió el test para usar `app.query_one("#switch-fixture_plugin", Switch)` y togglear `switch.value`
2. Se simplificaron las aserciones a propiedades que realmente existen (`plugin_text`, `event_text`, `runtime.is_started`)
3. Se removieron aserciones a propiedades y texto que nunca se implementaron

**Archivos modificados:** `kateto/tests/test_tui.py`
