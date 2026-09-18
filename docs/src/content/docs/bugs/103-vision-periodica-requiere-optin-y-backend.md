---
id: 103
title: "Describe periódico de visión no corre sin `vision_periodic` por voz ni backend de descripción"
severity: Media
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-17
---

## 103. Describe periódico de visión no corre sin `vision_periodic` por voz ni backend de descripción

**Severidad:** Media
**Componente:** `kateto/plugins/executor/static_vision_plugin.py`

### Descripción

`[plugin.executor_vision]` con `source_default`/`window_secs`/`capture_fps`/`describe_interval`/etc. no producía ningún `describe` automático. Las claves de plugin solo afinan captura y descripción; el schedule lo construye `create_plugins` ÚNICAMENTE para voces con `vision_periodic = true` (ninguna lo tenía), y el describe necesita `vision_endpoint`+`vision_model` o el sidecar video-rag (ninguno configurado → solo texto `recap`).

### Impacto

Cero narración ambiental; confusión porque la config "parece completa".

### Causa

Opt-in por voz no documentado en el momento de configurar (está en `docs/plugins/vision.md` pero nada lo advierte en runtime), y cadena de fallback silenciosa hasta `recap`.

### Solución aplicada

- Warnings en `StaticVisionPlugin.enable`: sin voces opt-in avisa que `describe_interval`/`window_secs` solos no agendan nada; sin VLM avisa que solo queda sidecar o recap.
- Queda en el usuario: `vision_periodic = true` (+ `vision_interval`) por voz, y un backend (`vision_endpoint`/`vision_model` o binario `video-rag`).

**Regresión:** `test_vision_enable_warns_without_optin_or_backend`, `test_vision_enable_quiet_with_optin_and_backend`.

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/tests/test_voice_vision_memory.py`
