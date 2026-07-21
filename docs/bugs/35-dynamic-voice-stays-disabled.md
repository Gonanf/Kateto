---
id: 35
title: "La voz activada dinámicamente sigue apareciendo deshabilitada"
severity: Alta
status: resolved
component: kateto/run_mode.py
resolved: 2026-07-21
---

## 35. La voz activada dinámicamente sigue apareciendo deshabilitada

**Severidad:** Alta
**Componente:** `kateto/run_mode.py`

### Descripción

Cuando un workflow llamaba a una voz configurada como deshabilitada, el
runtime la creaba y habilitaba, pero la TUI continuaba mostrándola como
deshabilitada y el estado de runtime no exponía el plugin recién creado.

### Impacto

La coordinación parecía fallar: la voz llamada no aparecía activa en la TUI y
las superficies que usaban `RuntimeOwner` podían observar el estado estático
del TOML en lugar del estado real del bus.

### Causa

`RuntimeOwner.voice_enabled()` consultaba siempre la configuración inicial,
por lo que devolvía `false` después de una habilitación dinámica. Además,
`runtime_plugins` devolvía únicamente la tupla de plugins descubiertos durante
el arranque y no incluía las voces añadidas al `PluginManager`.

### Solución aplicada

El estado de una voz ahora se resuelve primero contra los plugins activos del
manager, incluyendo coincidencias por nombre técnico y display name. La
colección `runtime_plugins` combina los plugins iniciales con los que el bus
registra dinámicamente.

### Archivos

`kateto/run_mode.py`, `kateto/tests/test_run_orchestration.py`
