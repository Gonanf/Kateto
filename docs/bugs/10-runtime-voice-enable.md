---
id: 10
title: "Voices no se pueden habilitar/deshabilitar en runtime"
severity: Alta
status: resolved
component: kateto/voices/factory.py, kateto/core/manager.py
---

## 10. Voices no se pueden habilitar/deshabilitar en runtime — ✅ RESUELTO

**Severidad:** Alta
**Componente:** `kateto/voices/factory.py`, `kateto/core/manager.py`

Las voces (doktor, conquest) son configuradas como `enabled = false` en `config.toml`. No hay manera de habilitarlas en runtime sin recargar la configuración completa. El tool `enable_plugin` solo funciona con instancias de `Plugin` registradas en `PluginManager`, pero las voces se crean en `create_voice()` solo cuando `enabled = true` en el config.

**Evidencia:**
```
# config.toml
[voice.doktor]
enabled = false

# enable_plugin("voice_doktor") -> "plugin 'voice_doktor' not found"
# porque doktor nunca se creó como Plugin
```

**Impacto:** Jane no puede habilitar doktor o conquest dinámicamente. Los workflows que requieren `calls_voices: ["Doktor"]` o `["Conquest"]` no pueden ejecutarse si esas voces están deshabilitadas.

**Solución aplicada:**
1. `VoiceEnableData(voice_name, enable)` en `core/event.py`
2. `_VoiceManagerPlugin` en `run_mode.py` registra el evento `voice_enable` y lo maneja
3. `RuntimeOwner.on_voice_enable()` busca la voz existente (re-enable) o la crea via `create_voice()` y la habilita
4. El MCP server expone `voice_enable` como tool automáticamente (via `refresh_tools()`)

**Archivos modificados:** `kateto/core/event.py`, `kateto/run_mode.py`

**Fix:**
1. Se agregó `VoiceEnableData(voice_name: str, enable: bool)` en `core/event.py`
2. Se creó `_VoiceManagerPlugin` (plugin interno) que registra el evento `voice_enable` y lo maneja
3. `RuntimeOwner.on_voice_enable()` busca la voz en plugins existentes (la re-enable si existe) o la crea vía `create_voice()` y la registra en el manager
4. El MCP server expone `voice_enable` como tool automáticamente

**Archivos:** `kateto/core/event.py`, `kateto/run_mode.py`

**Evidencia:** Jane puede llamar `voice_enable(voice_name="doktor")` vía MCP tool. Si doktor no está creado, se crea y habilita. Si ya existe pero deshabilitado, se re-enable.
