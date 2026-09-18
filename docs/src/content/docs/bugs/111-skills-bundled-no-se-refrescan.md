---
id: 111
title: "Las skills bundled no se refrescan: la copia del usuario queda vieja"
severity: Media
status: resolved
component: kateto/voices/skills.py
resolved: 2026-09-18
---

## 111. Las skills bundled no se refrescan: la copia del usuario queda vieja

**Severidad:** Media
**Componente:** `kateto/voices/skills.py`

### Descripción

El backfill de skills bundled (`ensure_shared_skill`, llamado desde `StaticVisionPlugin.initialize()`)
era copy-missing-only: si el archivo ya existía en la config del usuario, nunca se tocaba. Una skill
bundled que mejora en el repo quedaba vieja en la config del usuario para siempre.

Medido en el runtime real del usuario: `~/.config/kateto/skills/look-at/SKILL.md` = 1322 bytes contra
1918 del repo; lo que faltaba era exactamente la sección `## How to trigger a look` — la que dice que
la mirada se pide con `send_event(event_name="vision_describe_request", data={"requester","source"})`.

### Impacto

La voz contestaba *"no tengo herramienta para ver las pantallas"*. El tool existe (se genera un tool
por evento registrado y `vision_describe_request` está registrado mientras el plugin de visión vive);
lo que no existía era la instrucción, porque su skill era vieja. Las otras cuatro skills compartidas
estaban idénticas al repo: el drift fue sólo en `look-at`.

### Causa

`bootstrap_config` hace early-return cuando `config.toml` existe, y `ensure_shared_skill` sólo copiaba
el archivo faltante. Ningún path refrescaba el contenido cuando el bundle avanzaba.

### Solución aplicada

`ensure_shared_skill` deja de ser copy-missing-only: si el archivo del bundle difiere del de la config
del usuario, lo refresca guardando un backup `SKILL.md.bak.<timestamp>` al lado (nunca se borra ni se
pisa: ante colisión se sufija `.<n>`) y loguea `[skills] refreshed <name> (bundled changed)`. Límites:
sólo nombres con fuente bundled (las skills de usuario/`create_skill`/`update_skill` sin bundle dan
`SkillLoadError` y no se tocan); archivo idéntico = no-op silencioso. El `--force` del CLI `install` y
el copy-missing de packs no cambian de semántica.

**Regresión:** `test_backfill_refreshes_stale_bundled_skill`,
`test_backfill_identical_skill_untouched`, `test_backfill_leaves_user_skill_intact`,
`test_refresh_is_idempotent` en `kateto/tests/test_vision_skill.py`.

**Archivos:** `kateto/voices/skills.py`, `kateto/tests/test_vision_skill.py`
