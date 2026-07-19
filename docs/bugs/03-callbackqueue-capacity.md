---
id: 3
title: "CallbackQueue con capacity fijo en 32"
severity: Baja
status: resolved
component: kateto/plugins/audio_input/base.py
---

## 3. CallbackQueue con capacity fijo en 32 — ✅ RESUELTO

**Severidad:** Baja (visible en condiciones de carga alta)
**Componente:** `kateto/plugins/audio_input/base.py`

La clase `CallbackQueue` tiene un `capacity=32` hardcodeado. No es configurable desde `config.toml` ni desde `PluginSettings`.

```python
self._callback_queue = CallbackQueue(capacity=32)
```

**Impacto:** En ráfagas largas de audio o cuando el pipeline de procesamiento está congestionado, se dropean frames de audio (`dropped_frames` se incrementa pero no hay notificación). El audio se corta sin que el usuario lo sepa.

**Causa:** decisión de diseño inicial para límite de memoria. No se expuso como parámetro de configuración.

**Solución aplicada:** Se agregó `callback_queue_capacity` en `PluginSettings` (config.py), `AudioInputConfig` (base.py), y se usa en `listener.py` en vez del hardcode 32.

**Fix:** Se agregó `callback_queue_capacity` (opcional, default 32) a `PluginSettings` y `AudioInputConfig`. `AudioInputPlugin` ahora usa `self._config.callback_queue_capacity` en vez del valor hardcodeado.

**Archivos:** `kateto/core/config.py`, `kateto/plugins/audio_input/base.py`, `kateto/plugins/audio_input/listener.py`

**Evidencia:** El campo se expone desde config y se pasa al constructor de `CallbackQueue`. Si no se especifica, usa default 32 (mismo comportamiento anterior).
