---
id: 24
title: "TUI: conflictos de nombres entre voces activadas y plugins auto-detectados (jane vs voice_jane)"
severity: Media
status: resolved
component: kateto/plugins/system/tui.py
resolved: 2026-07-19
---

## 24. TUI: conflictos de nombres entre voces activadas y plugins auto-detectados (jane vs voice_jane)

**Severidad:** Media
**Componente:** `kateto/plugins/system/tui.py` (método `_available_plugins`)

### Descripción

En el TUI, las voces que están **activadas desde la configuración inicial** aparecen con nombres conflictivos en la sección de Plugins. El problema:

- Una voz como `jane` habilitada en `config.toml` se registra en el manager como plugin con nombre `jane` (porque `create_voice()` registra el plugin con el nombre de la voz)
- En `_available_plugins()`, las voces del config se agregan como `voice_{name}` (e.g. `voice_jane`)
- Resultado: aparecen **dos entradas** en la lista de plugins: `jane` y `voice_jane`
- Con las voces **deshabilitadas** en config no ocurre, porque no se registran como plugin en el manager (solo aparecen como `voice_jane` desde el loop de config)

### Impacto

- Confusión visual en el TUI: el usuario ve duplicados
- Ruido en la interfaz que dificulta identificar plugins reales
- Inconsistencia: las voces habilitadas se muestran de dos formas distintas
- Dificulta el debugging porque no está claro cuál de las dos entradas es la "real"

### Causa

`_available_plugins()` en `tui.py` (líneas 597-614) tiene dos fuentes de plugins:

1. `manager.get_plugins()` — incluye las voces registradas como plugins con su nombre limpio (e.g. `jane`)
2. Loop de `config.settings.voice` — agrega TODAS las voces como `voice_{name}` (e.g. `voice_jane`), independientemente de si ya existen en el manager

### Posible solución

Opción A (recomendada): En `_available_plugins()`, al iterar `config.settings.voice`, verificar si el nombre base ya existe como plugin en el manager antes de agregar la versión `voice_{name}`:

```python
for name in config.settings.voice:
    if name in plugins:  # ya registrado como plugin por la voz
        continue
    plugin_name = f"voice_{name}"
    if plugin_name not in plugins:
        p = Plugin(plugin_name)
        p.enabled = config.settings.voice[name].enabled
        plugins[plugin_name] = p
```

Opción B: Cambiar el naming scheme para que sea consistente (todas las voces como `voice_jane` en el manager, o todas como `jane`).

Opción C: Agregar un flag en el Plugin para indicar si es "voz" o "plugin puro", y filtrar en la UI.

**Archivos:** `kateto/plugins/system/tui.py`

### Solución aplicada

Se agregó una línea en el loop `for name in config.settings.voice:` de `_available_plugins()`: antes de crear la entrada `voice_{name}`, se verifica si `name in plugins` (el nombre base, ej. `jane`, ya está registrado como plugin por el sistema de voces). Si ya existe, se salta con `continue`. Así solo aparecen `voice_{name}` para las voces que NO están habilitadas como plugins (deshabilitadas en config).

```python
for name in config.settings.voice:
    if name in plugins:
        continue
    plugin_name = f"voice_{name}"
    ...
```

**Archivos:** `kateto/plugins/system/tui.py`
