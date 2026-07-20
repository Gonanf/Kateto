---
id: 23
title: "Nuevo plugin VoiceSOULManager: gestión centralizada de SOUL/JOURNAL/workflows"
severity: Media
status: resolved
component: kateto/plugins/voice_soul_manager/
resolved: 2026-07-19
---

## 23. Nuevo plugin VoiceSOULManager: gestión centralizada de SOUL/JOURNAL/workflows

**Severidad:** Media
**Componente:** `kateto/plugins/voice_soul_manager/`

### Descripción

Actualmente cada voz maneja su propio SOUL.md y JOURNAL.md a través de `VoiceMemory` y `VoiceToolExecutor`. Esto descentraliza la lógica de actualización del estado persistente de cada voz, generando duplicación de responsabilidades y potenciales inconsistencias cuando múltiples voces están idle simultáneamente.

Se propone un nuevo **plugin centralizado** (`voice_soul_manager`) que:

- Escucha eventos de estado de las voces (idle, thinking, waiting, etc.)
- Cuando una voz está **idle**, verifica si es momento de actualizar sus datos
- Decide automáticamente qué actualizar: SOUL.md, JOURNAL.md, workflows, skills, etc.
- Centraliza la lógica de "mantenimiento de voz" que hoy está dispersa en `VoiceMemory`, `VoiceToolExecutor` y las tools de cada voz
- Las voces conservan acceso a tools específicas de SOUL/JOURNAL para updates explícitos, pero la gestión automática pasa al plugin

### Impacto

- Elimina duplicación de lógica entre voces
- Un solo punto de control para actualizaciones automáticas
- Las voces dejan de tener que auto-gestionarse cuando están idle
- Preparación del terreno para sistemas más complejos (priorización de updates, colas, reconciliación de cambios)
- Previene condiciones de carrera cuando dos voces intentan actualizar el mismo archivo

### Causa

Diseño inicial donde cada voz es responsable de su propia persistencia. Funciona para el MVP pero no escala a medida que se agregan más voces o workflows.

### Solución aplicada

Se creó el plugin `voice_soul_manager` en `kateto/plugins/voice_soul_manager/` con:

1. **`__init__.py`** — Clase `VoiceSOULManager(Plugin)` que:
   - Escucha eventos `voice_idle` (emitidos por `VoiceAgent` al finalizar generación)
   - Delega en `VoiceUpdateTracker` para throttle time-based (5 min por defecto)
   - Delega en `VoiceUpdater` para las operaciones de escritura
   - Factory `create_plugins(ctx)` sigue el patrón estándar de discovery

2. **`scheduler.py`** — `VoiceUpdateTracker`:
   - `dict[str, datetime]` con timestamp de última actualización por voz
   - `should_update(voice)` → True si nunca se actualizó o pasó el intervalo
   - `mark_updated(voice)` → registra timestamp
   - Intervalo default: 300s (5 min)

3. **`updater.py`** — `VoiceUpdater`:
   - `append_idle_entry(voice)` → usa `VoiceMemory.append_journal()` para agregar `[auto] voice_idle at {timestamp}`
   - `touch_soul(voice)` → lee SOUL.md, si está vacío escribe uno mínimo con `last_active`; si tiene contenido, agrega o actualiza la línea `> last_active: {timestamp}`
   - Usa `VoiceMemory.for_voice()` para path isolation

4. **`config/defaults/config.toml`** — Se agregó entrada `[plugin.voice_soul_manager] enabled = true`

**Detalles de implementación:**

- No requiere nuevos eventos — `voice_idle` ya está registrado por `VoiceAgent`
- El plugin se auto-descubre via `_scan_plugins()` al tener `create_plugins()` en su `__init__.py`
- Respeto de aislamiento: `VoiceMemory.for_voice()` + `VoiceFileStore` previenen escrituras fuera del directorio de la voz
- Throttle previene actualizaciones constantes: una voz que vuelve a idle rápidamente no genera entrada en JOURNAL.md hasta pasado el intervalo

**Próximos pasos (fuera de scope actual):**
- Actualización inteligente de SOUL.md vía LLM (resumir actividad reciente)
- Soportar thresholds configurables desde `config.toml`
- Detectar workflows completados como trigger de actualización
- Broadcasting de eventos `soul_updated` para hot-reload/TUI

**Archivos:** `kateto/plugins/voice_soul_manager/__init__.py`, `kateto/plugins/voice_soul_manager/scheduler.py`, `kateto/plugins/voice_soul_manager/updater.py`, `config/defaults/config.toml`
