---
id: 12
title: "TODO.md se escribe en voices/shared/ no en la raíz del config"
severity: Informativa
status: open
component: kateto/plugins/executor/todo_list.py
---

## 12. TODO.md se escribe en voices/shared/ no en la raíz del config

**Severidad:** Informativa
**Componente:** `kateto/plugins/executor/todo_list.py`

Los items de TODO se almacenan en `~/.config/kateto/voices/shared/TODO.md`, no en `~/.config/kateto/TODO.md`. Esto es porque `TodoListExecutor` usa `VoiceFileStore.for_voice(voice="shared")`.

**Evidencia:**
```
~/.config/kateto/voices/shared/TODO.md:
  - [ ] preparar presentación del sprint
  - [ ] revisar pull requests del equipo
```

**Causa:** Diseño intencional — los TODO items están scoped por voz. La voz "shared" es el default para items no específicos.

**Impacto:** Los usuarios pueden buscar TODO.md en la ubicación equivocada. No es un bug funcional.
