---
id: 14
title: "Sin herramientas para crear/modificar Skills, Workflows y Voces desde el runtime"
severity: Media
status: resolved
component: kateto/voices/tools.py, kateto/core/workflow.py
resolved: 2026-07-19
---

## 14. Sin herramientas para crear/modificar Skills, Workflows y Voces desde el runtime

**Severidad:** Media
**Componente:** `kateto/voices/tools.py`, `kateto/core/workflow.py`

Actualmente no hay manera de que una voz (o el usuario a través de una voz) cree, modifique o elimine:
- **Skills** (archivos SKILL.md)
- **Workflows** (archivos workflow.py)
- **Voces** (archivos SOUL.md + config)

Todo requiere edición manual de archivos en `~/.config/kateto/`.

**Impacto:**
- Jane no puede crear un nuevo skill para doktor sin acceso al filesystem
- No se pueden definir workflows dinámicamente durante una sesión
- Las voces no pueden evolucionar sus propias instrucciones

**Solución propuesta:** Agregar tools al VoiceToolExecutor:

```python
# Tools a agregar:
"create_skill"     # Crea ~/.config/kateto/skills/{name}/SKILL.md
"update_skill"     # Modifica un SKILL.md existente
"create_workflow"  # Crea ~/.config/kateto/voices/{voice}/workflows/{name}/workflow.py
"update_workflow"  # Modifica un workflow.py existente
"update_soul"      # Modifica ~/.config/kateto/voices/{name}/SOUL.md
```

**Seguridad:** Estos tools deben:
1. Validar que las rutas no escapen `config_dir`
2. Hacer backup antes de modificar
3. Emitir eventos `skill_created`, `workflow_created` para hot-reload
4. Estar sujetos a confirmación del usuario (opcional)
