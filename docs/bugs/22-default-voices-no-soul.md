---
id: 22
title: "config/defaults/voices/ no incluye SOUL.md para jane, doktor, conquest"
severity: Media
status: resolved
component: config/defaults/voices/
resolved: 2026-07-19
---

## 22. config/defaults/voices/ no incluye SOUL.md para jane, doktor, conquest

**Severidad:** Media
**Componente:** `config/defaults/voices/`

### Descripción

Los directorios de voces en `config/defaults/voices/` solo contienen `workflows/`. Falta `SOUL.md` para las tres voces (jane, doktor, conquest). El sistema es resiliente (`VoiceMemory.ensure_soul()` lo crea desde el `system_prompt` del perfil), pero los defaults deberían incluir el archivo para consistencia y para que la copia inicial al user config lo tenga explícito.

### Impacto

- En el primer bootstrap, la voz arranca sin SOUL.md explícito.
- `ensure_soul()` lo genera automáticamente desde el `system_prompt` de `factory.py`, así que no hay error funcional.
- Inconsistencia con `~/.config/kateto/voices/jane/SOUL.md` y `doktor/SOUL.md` que sí existen (creados por `ensure_soul()` en ejecuciones previas).

### Causa

Omisión durante la configuración inicial de defaults. Los `system_prompt` existen en `kateto/voices/factory.py` pero nunca se materializaron como archivos en `config/defaults/voices/`.

### Solución aplicada

Agregado `SOUL.md` en cada directorio de voz con el contenido exacto del `system_prompt` de su perfil:

- `config/defaults/voices/jane/SOUL.md` → `"You are Jane, Kateto's calm orchestration partner..."` (factory.py:12)
- `config/defaults/voices/doktor/SOUL.md` → `"You are Doktor, Kateto's delivery advisor..."` (factory.py:19)
- `config/defaults/voices/conquest/SOUL.md` → `"You are Conquest, Kateto's agile facilitator..."` (factory.py:26)

**Archivos:** `config/defaults/voices/{jane,doktor,conquest}/SOUL.md`
