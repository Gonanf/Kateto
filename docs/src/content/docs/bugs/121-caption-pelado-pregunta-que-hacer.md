---
id: 121
title: "La voz recibe el caption de visión como dato pelado y pregunta qué hacer con él"
severity: Alta
status: resolved
component: kateto/voices/base.py
resolved: 2026-09-18
---

## 121. La voz recibe el caption de visión como dato pelado y pregunta qué hacer con él

**Severidad:** Alta
**Componente:** `kateto/voices/base.py` (marco), `kateto/plugins/executor/static_vision_plugin.py` (emisor, sin cambios), `config/defaults/skills/look-at/SKILL.md`

### Descripción

El usuario reportó (textual): "El agente no sabe que hacer con esta información
que tiene del vídeo rag, por lo que dice (en inglés encima) 'What do you want
me to do with this information?'".

### Impacto

Cada narración ambiental sonaba a error: la voz pedía instrucciones en inglés
en vez de comentar lo que veía en personaje y en el idioma del proyecto.

### Causa

1. La narración ambiental emitía el caption como dato pelado
   (`on_vision_describe_request`): `GenerateData(prompt=f"[look-at …]: {fused}")`,
   sin nada que diga qué es ni qué hacer con eso.
2. La skill `look-at` sólo guiaba el caso pedido por el usuario; la narración
   ambiental no tiene disparador conversacional.
3. `VoiceAgent.on_vision_describe_result` es no-op: la descripción sólo caía en
   memoria, sin armar turno con instrucción.
4. Sin instrucción en el turno, el modelo chico de voz defaultea al inglés pese
   a la regla general del prompt estable (`context.py`).

### Solución aplicada

Marco en la voz —opción (b)— y no en el plugin: sólo la voz sabe su idioma
(`response_language`) y su persona, y un único punto cubre narración
ambiental (`_messages_for`, sobre el prompt `[look-at …]`) y resultado pedido
(`_remember_event`, sobre `VisionDescribeResultData`). El plugin sigue
mandando el caption pelado. El marco dice: mirada propia, comentar en 1-2
frases en personaje, prohibido pedir instrucciones, no inventar, idioma
explícito (`en` → inglés; otro/ausente → español, lengua del proyecto).
Viaja en el turno volátil (mensaje user / historial); el prompt estable
congelado no cambia.

**Regresión:** `kateto/tests/test_vision_turn_framing.py` (5 tests: marco
ambiental + caption intacto, charla normal sin envolver, idioma desde config,
resultado pedido enmarcado, idempotencia).

**Archivos:** `kateto/voices/base.py`, `kateto/tests/test_vision_turn_framing.py`,
`config/defaults/skills/look-at/SKILL.md`, `docs/src/content/docs/plugins/vision.md`
