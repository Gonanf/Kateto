---
id: 13
title: "Archivos y carpetas duplicadas en múltiples ubicaciones"
severity: Crítica
status: resolved
component: raíz del proyecto + config/defaults/
resolved: 2026-07-19
---

## 13. Archivos y carpetas duplicadas en múltiples ubicaciones

**Severidad:** Crítica
**Componente:** Raíz del proyecto, `config/defaults/`

### Duplicación de voces

| Ubicación | Contenido |
|-----------|-----------|
| `voices/` (raíz) | `conquest/`, `doktor/`, `jane/` (cada una con reference.wav + SOUL.md) |
| `config/defaults/voices/` | `Conquest/` (workflows), `Doktor/` (workflows) — capitalizadas |

**Problema:** La raíz `voices/` contenía archivos de workspace del desarrollador (reference.wav, SOUL.md) que no son referenciados por ningún código. Además, `config/defaults/voices/Conquest/` y `config/defaults/voices/Doktor/` usaban mayúscula inicial, pero el runtime busca directorios por el nombre del config key (minúscula: `voice.conquest`). En filesystems case-sensitive (Linux), `VoiceFileStore` crea `config_dir / "voices" / voice` con el key lowercase, y si el directorio tiene mayúscula no lo encuentra.

### Duplicación de skills

| Ubicación | Contenido |
|-----------|-----------|
| `skills/` (raíz) | `orchestrator/`, `backlog/`, `risk-analysis/`, `planning-poker/` |
| `config/defaults/skills/` | mismos 4 skills (SKILL.md) |
| `~/.config/kateto/skills/` | Copia via bootstrap |

**Problema:** La raíz `skills/` es una copia estática de `config/defaults/skills/`. El código (`VoiceToolExecutor`) carga skills desde `config_dir`, no desde la raíz del proyecto.

### Duplicación de scripts

| Ubicación | Contenido |
|-----------|-----------|
| `script/` | `qa/web-terminal-visual-qa.mjs`, `qa/web-terminal-visual-qa.test.mjs` |
| `scripts/` | `qa/` (vacío) |

**Problema:** `script/` tiene archivos, `scripts/` está vacío.

### Duplicación de TODO.md

| Ubicación | Contenido |
|-----------|-----------|
| `./TODO.md` (raíz) | Items de TODO estáticos del proyecto |
| `~/.config/kateto/voices/shared/TODO.md` | Items de TODO dinámicos del sistema |

**Problema:** Dos TODO.md con contenido diferente. El runtime usa el del user config.

### Duplicación de workflows

| Ubicación | Contenido |
|-----------|-----------|
| `config/defaults/voices/*/workflows/` | 4 workflows (Doktor: 2, Conquest: 2) |
| `~/.config/kateto/voices/*/workflows/` | 4 workflows (mismos) |
| `~/.config/kateto/workflows/` | daily-standup/ (vacío) |

**Problema:** Los workflows existen en defaults y se copian a user config vía bootstrap.

### Impacto

- Desarrolladores no saben dónde editar (¿raíz? ¿defaults? ¿user config?)
- `skills/` raíz: cambios no se reflejan en el runtime (carga desde `config_dir`)
- `voices/` raíz: no referenciado por ningún código, solo ocupa espacio
- `config/defaults/voices/` con mayúscula: no coincide con el key lowercase del runtime en Linux

### Solución aplicada

1. **Eliminado** `skills/` de la raíz (código carga desde `config_dir/skills/`)
2. **Eliminado** `scripts/` (vacío), se mantiene `script/`
3. **Eliminado** `voices/` de la raíz (archivos de workspace no referenciados)
4. **Renombrado** `config/defaults/voices/Conquest/` → `conquest/` (casefold-safe, coincide con key `voice.conquest`)
5. **Renombrado** `config/defaults/voices/Doktor/` → `doktor/`
6. **Eliminado** `TODO.md` de la raíz (el runtime usa `voices/shared/TODO.md` en user config)
7. **NO se movió** `config/defaults/` — el bootstrap ya copia a user config en primera ejecución

### Orden de precedencia documentado

```
1. User config (~/.config/kateto/… o $XDG_CONFIG_HOME/kateto/…)
2. Defaults (config/defaults/ — bootstrap template)
3. Hardcoded (factory.py, perfiles de voz)
```

**Referencias en código al directorio de voces:** `kateto/core/storage.py:87`, `kateto/voices/base.py:164`, `kateto/voices/memory.py:22`, `kateto/plugins/system/mcp_server.py:123`, `kateto/plugins/executor/todo_list.py:44` — todos usan `config_dir / "voices" / voice` donde `voice` es el key lowercase del `config.toml`.
