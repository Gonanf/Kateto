---
id: 102
title: "El modelo no sabe que puede mirar: skill sin mecanismo y voz que ignora vision_describe_result"
severity: Alta
status: resolved
component: kateto/voices/base.py, config/defaults/skills/look-at/SKILL.md
resolved: 2026-09-17
---

## 102. El modelo no sabe que puede mirar: skill sin mecanismo y voz que ignora vision_describe_result

**Severidad:** Alta
**Componente:** `kateto/voices/base.py`, `config/defaults/skills/look-at/SKILL.md`

### Descripción

Ante "fíjate el tema del video", el modelo respondía que no tiene herramienta "Describe" y pedía más información, aunque el plugin `static_vision` y el sidecar `video-rag` existen. Tres capas rotas a la vez:

1. El skill `look-at` describía la semántica (`source="auto"`) pero nunca decía CÓMO disparar la mirada (sin tool dedicada; el mecanismo real es `send_event` → `vision_describe_request`).
2. `VoiceAgent` no tenía handler `on_vision_describe_result` (sin suscripción) y `_remember_event` ignoraba `VisionDescribeResultData`: aunque el resultado llegara al bus, jamás entraba en la memoria de la voz.
3. Ninguna voz listaba `video_rag` en `mcp_servers` (solo `"system"`) y el binario `video-rag` ni siquiera está instalado: sin cliente MCP registrado, ni el modelo ve sus tools ni el fallback `describe_images` del plugin de visión puede llamarlo.

### Impacto

El modelo no puede iniciar un look on-demand ni usar `search`/`answer` de video-rag; solo recibe descripciones si otro path se las inyecta como prompt.

### Causa

Wiring incompleto entre skill → evento → memoria → MCP, más dependencia externa ausente.

### Solución aplicada

- `VoiceAgent.on_vision_describe_result` (no-op para auto-suscripción) + caso en `_remember_event` que guarda `[look-at <source> <span>s]: <texto>` como mensaje de usuario (misma semántica que las transcripciones broadcast).
- Skill documenta el trigger: `list_events` → `send_event vision_describe_request {requester, source}`; el resultado cae en memoria.
- Queda en el usuario: instalar `video-rag` y añadir `"video_rag"` a `mcp_servers` de las voces que deban verlo.

**Regresión:** `test_voice_receives_and_remembers_vision_result`.

**Archivos:** `kateto/voices/base.py`, `config/defaults/skills/look-at/SKILL.md`, `kateto/tests/test_voice_vision_memory.py`
