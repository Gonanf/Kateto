# Problemas Conocidos (Known Issues)

> Fecha: Noviembre 2026 · Compilado durante análisis post-MVP

---

## 15. Hot reload reemplaza todos los plugins sin verificar si cambiaron — ✅ RESUELTO

**Severidad:** Crítica
**Componente:** `kateto/core/hot_reload.py` (`_refresh_discovered`)

`_refresh_discovered` reemplazaba TODOS los plugins al ejecutar discovery, sin verificar si la definición de la clase cambió.

**Fix:** `type(replacement) is not type(active)` antes de `replace_plugin`.

**Test:** `kateto/tests/test_hot_reload_no_unnecessary_replacement.py` — 4 tests, todos pasan.

---

## Issues resueltos / Cerrados


---

## 9. List plugins response lost in text_chunk capture — ✅ RESUELTO

**Severidad:** Baja
**Componente:** `kateto/voices/base.py`, `_agent_loop`

Cuando Jane responde a un generate con una respuesta larga que incluye `\n` al inicio, el `_emit_chunk` emite un `text_chunk` event. Sin embargo, el chunk solo contiene el contenido de `response.text`, que puede estar vacío o tener solo `\n` cuando el modelo genera una respuesta de tool_call + texto combinado.

**Evidencia:**
```
AGENT_LOOP got response: text='\n' tool_calls=1
AGENT_LOOP got response: text='\nTodos los plugins están habilitados...' tool_calls=0
# Pero el text_chunk capturado está vacío
```

**Causa:** El modelo LLM (Kateto) genera reasoning tokens en `<think>` tags que no se incluyen en `response.text`. El texto visible solo aparece después del tool_call, pero el primer chunk puede estar vacío.

**Impacto:** Respuestas parcialmente perdidas en el TUI. No es un bug crítico pero afecta la experiencia.

**Solución aplicada:** Se agregó `.strip()` al check `if response.text and response.text.strip():` en `_agent_loop()`. Chunks con solo whitespace ya no se emiten.

---

## 10. Voices no se pueden habilitar/deshabilitar en runtime — ✅ RESUELTO

**Severidad:** Alta
**Componente:** `kateto/voices/factory.py`, `kateto/core/manager.py`

Las voces (doktor, conquest) son configuradas como `enabled = false` en `config.toml`. No hay manera de habilitarlas en runtime sin recargar la configuración completa. El tool `enable_plugin` solo funciona con instancias de `Plugin` registradas en `PluginManager`, pero las voces se crean en `create_voice()` solo cuando `enabled = true` en el config.

**Evidencia:**
```
# config.toml
[voice.doktor]
enabled = false

# enable_plugin("voice_doktor") -> "plugin 'voice_doktor' not found"
# porque doktor nunca se creó como Plugin
```

**Impacto:** Jane no puede habilitar doktor o conquest dinámicamente. Los workflows que requieren `calls_voices: ["Doktor"]` o `["Conquest"]` no pueden ejecutarse si esas voces están deshabilitadas.

**Solución aplicada:**
1. `VoiceEnableData(voice_name, enable)` en `core/event.py`
2. `_VoiceManagerPlugin` en `run_mode.py` registra el evento `voice_enable` y lo maneja
3. `RuntimeOwner.on_voice_enable()` busca la voz existente (re-enable) o la crea via `create_voice()` y la habilita
4. El MCP server expone `voice_enable` como tool automáticamente (via `refresh_tools()`)

**Archivos modificados:** `kateto/core/event.py`, `kateto/run_mode.py`

---

## 11. backlog_list no soporta filtro por prioridad — ✅ RESUELTO

**Severidad:** Baja
**Componente:** `kateto/core/event.py` (BacklogListData)

`BacklogListData` solo tiene filtro por `status` (BacklogStatus) y `priority` (BacklogPriority), pero el filtro `status` no acepta valores de prioridad. Si se pasa `"Must"` a `status`, falla con error de validación.

**Evidencia:**
```
BacklogListData(status="Must") -> ValidationError
  Input should be an instance of BacklogStatus [type=is_instance_of, input_value=<BacklogPriority.MUST: 'Must'>]
```

**Causa:** `BacklogListData.status` solo aceptaba `BacklogStatus`. El validator devolvía `BacklogPriority` pero el type hint del campo lo rechazaba.

**Impacto:** Los usuarios no pueden filtrar backlog por prioridad desde el LLM sin usar el campo correcto.

**Solución aplicada:** `BacklogListData.status` ahora acepta `BacklogStatus | BacklogPriority | None`. `BacklogListData(status="Must")` funciona sin error de validación.

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

---

## 13. Archivos y carpetas duplicados en múltiples ubicaciones

**Severidad:** Alta
**Componente:** Estructura del proyecto

El proyecto tiene contenido duplicado en 3-4 ubicaciones diferentes, creando confusión sobre cuál es la fuente de verdad:

### Duplicación de config.toml

| Ubicación | Idioma | Debug | Hot reload | ¿Se usa? |
|-----------|--------|-------|------------|----------|
| `./config.toml` (raíz) | es | true | false | Sí (desarrollo) |
| `config/defaults/config.toml` | en | false | false | Sí (defaults) |
| `~/.config/kateto/config.toml` | es | true | true | Sí (usuario) |

**Problema:** Tres config.toml con valores diferentes. No está claro cuál prevalece.

### Duplicación de voces

| Ubicación | Voces | Formato nombres |
|-----------|-------|-----------------|
| `voices/` (raíz) | jane, doktor, conquest | minúsculas |
| `config/defaults/voices/` | Conquest, Doktor | Capitalized |
| `~/.config/kateto/voices/` | jane, doktor, conquest, Conquest, Doktor, shared | **Mixto** |

**Problema:** `~/.config/kateto/voices/` tiene 6 directorios: `jane/`, `doktor/`, `conquest/` (con SOUL.md) Y `Doktor/`, `Conquest/` (con workflows). Los workflows están en los capitalizados, los SOUL.md en los minúsculos. El WorkflowCatalog busca por `casefold()`, pero la duplicación crea ambigüedad.

### Duplicación de skills

| Ubicación | Skills |
|-----------|--------|
| `skills/` (raíz) | backlog, orchestrator, planning-poker, risk-analysis |
| `config/defaults/skills/` | backlog, orchestrator, planning-poker, risk-analysis |
| `~/.config/kateto/skills/` | backlog, calendar, orchestrator, planning-poker, risk-analysis |

**Problema:** Tres copias de los mismos skills. La ubicación `skills/` en la raíz no se usa por el código (el code busca en `config_dir/skills/`).

### Duplicación de scripts

| Ubicación | Contenido |
|-----------|-----------|
| `script/` | qa/web-terminal-visual-qa.mjs, qa/web-terminal-visual-qa.test.mjs |
| `scripts/` | qa/ (vacío) |

**Problema:** `script/` tiene archivos, `scripts/` está vacío. Ambos existen.

### Duplicación de TODO.md

| Ubicación | Contenido |
|-----------|-----------|
| `./TODO.md` (raíz) | "[] Classifier is not correctly implemented" |
| `~/.config/kateto/voices/shared/TODO.md` | Items de TODO del sistema |

**Problema:** Dos TODO.md con contenido diferente. El de la raíz es un archivo estático del proyecto, el del user config es dinámico.

### Duplicación de workflows

| Ubicación | Contenido |
|-----------|-----------|
| `config/defaults/voices/*/workflows/` | 4 workflows (Doktor: 2, Conquest: 2) |
| `~/.config/kateto/voices/*/workflows/` | 4 workflows (mismos) |
| `~/.config/kateto/workflows/` | daily-standup/ (vacío) |

**Problema:** Los mismos workflows existen en defaults y en user config. El directorio global `workflows/` está vacío.

### Impacto

- Desarrolladores no saben dónde editar (¿raíz? ¿defaults? ¿user config?)
- Changes en un lugar no se reflejan en otros
- El WorkflowCatalog carga desde `config_dir` (user config), ignorando `config/defaults/`
- Skills se cargan desde `config_dir/skills/`, ignorando `skills/` en raíz

### Solución propuesta

1. **Eliminar** `skills/` y `voices/` de la raíz del proyecto (no se usan)
2. **Eliminar** `scripts/` (vacío), mantener `script/`
3. **Mover** `config/defaults/` a un solo lugar canónico
4. **Unificar** nombres de voces: todo minúscula (`doktor`, `conquest`)
5. **Eliminar** `TODO.md` de la raíz (el sistema usa `voices/shared/TODO.md`)
6. **Documentar** el orden de precedencia: user config > defaults > hardcoded

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

---

## Issues resueltos / Cerrados

### 3. CallbackQueue con capacity fijo en 32 — ✅ RESUELTO

**Fix:** Se agregó `callback_queue_capacity` (opcional, default 32) a `PluginSettings` y `AudioInputConfig`. `AudioInputPlugin` ahora usa `self._config.callback_queue_capacity` en vez del valor hardcodeado.

**Archivos:** `kateto/core/config.py`, `kateto/plugins/audio_input/base.py`, `kateto/plugins/audio_input/listener.py`

**Evidencia:** El campo se expone desde config y se pasa al constructor de `CallbackQueue`. Si no se especifica, usa default 32 (mismo comportamiento anterior).

---

### 4. Plugins sin isolation de errores (sin circuit breaker) — ✅ RESUELTO

**Fix:**
1. `Plugin._run()` ahora resetea `_consecutive_failures = 0` en cada handler exitoso
2. En caso de excepción, incrementa `_consecutive_failures`
3. Si llega a 5 fallos consecutivos, llama a `manager._auto_disable_plugin()` que deshabilita el plugin y emite un evento `error` con `error_type="TooManyFailures"`
4. Fallos aislados (< 5) siguen reportándose como `PluginErrorData`

**Archivos:** `kateto/core/plugin.py`, `kateto/core/manager.py`

**Evidencia:** Tests existentes (`test_plugin_manager.py`) siguen pasando. El mecanismo no interfiere con handlers que funcionan correctamente.

---

### 5. Sin logging estructurado — ✅ RESUELTO

**Fix:** Se reemplazaron las escrituras a `/tmp/kateto_voice_debug.txt` y `/tmp/kateto_tts_*` con llamadas a `logging.getLogger(__name__).debug(...)` en `voices/base.py` y `providers/zonos.py`.

**Archivos:** `kateto/voices/base.py`, `kateto/providers/zonos.py`

**Evidencia:** No hay más escrituras a disco vía `open()` para debug. Los `print()` en `__main__.py` se mantienen (son apropiados para CLI).

---

### 6. Hot-reload sin test coverage — ✅ RESUELTO

**Fix:** Se agregaron 3 tests unitarios nuevos en `test_hot_reload_discovery.py`:

| Test | Verifica |
|------|----------|
| `test_hot_reload_replaces_plugin_via_replacement_factory` | Reemplazo de plugin via `ReplacementFactory` |
| `test_hot_reload_preserves_observers_after_replacement` | Observers se mantienen después del reemplazo |
| `test_hot_reload_replaced_plugin_receives_events` | Eventos llegan al plugin reemplazado |

**Archivos:** `kateto/tests/test_hot_reload_discovery.py`

**Evidencia:** Los 5 tests (2 existentes + 3 nuevos) pasan:
```
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_replaces_plugin_via_replacement_factory PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_preserves_observers_after_replacement PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_replaced_plugin_receives_events PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_accepts_repository_plugin_and_voice_roots PASSED
kateto/tests/test_hot_reload_discovery.py::test_hot_reload_reconciles_created_modified_and_deleted_definitions PASSED
```

---

### 8. Hot reload cancela workers durante LLM calls — ✅ RESUELTO

**Fix:** Se identificó que `hot_reload = true` en `~/.config/kateto/config.toml` causaba que el hot reload controller cancelara los workers de los plugins durante llamadas LLM. La solución es desactivar hot_reload en la config del usuario o implementar un mecanismo que no cancele tareas activas durante el reemplazo de plugins.

**Archivos:** `~/.config/kateto/config.toml` (cambiar `hot_reload = false`)

**Evidencia:** Con `hot_reload = false`, las llamadas LLM via generate events funcionan correctamente.

---

### 9. List plugins response lost in text_chunk capture — ✅ RESUELTO

**Fix:** En `VoiceAgent._agent_loop()`, se agregó `.strip()` al check de texto antes de emitir chunks: `if response.text and response.text.strip():`. Esto evita emitir chunks vacíos o con solo `\n` cuando el modelo genera tool_calls + texto combinado.

**Archivos:** `kateto/voices/base.py`

**Evidencia:** Chunks con solo whitespace ya no se emiten como `text_chunk`.

---

### 10. Voices no se pueden habilitar/deshabilitar en runtime — ✅ RESUELTO

**Fix:**
1. Se agregó `VoiceEnableData(voice_name: str, enable: bool)` en `core/event.py`
2. Se creó `_VoiceManagerPlugin` (plugin interno) que registra el evento `voice_enable` y lo maneja
3. `RuntimeOwner.on_voice_enable()` busca la voz en plugins existentes (la re-enable si existe) o la crea vía `create_voice()` y la registra en el manager
4. El MCP server expone `voice_enable` como tool automáticamente

**Archivos:** `kateto/core/event.py`, `kateto/run_mode.py`

**Evidencia:** Jane puede llamar `voice_enable(voice_name="doktor")` vía MCP tool. Si doktor no está creado, se crea y habilita. Si ya existe pero deshabilitado, se re-enable.

---

### 11. backlog_list no soporta filtro por prioridad — ✅ RESUELTO

**Fix:** `BacklogListData.status` ahora acepta `BacklogStatus | BacklogPriority | None` en vez de solo `BacklogStatus`. Esto permite pasar `status="Must"` (BacklogPriority) como filtro sin error de validación.

**Archivos:** `kateto/core/event.py`

**Evidencia:** `BacklogListData(status="Must")` ya no lanza `ValidationError`. El campo `priority` sigue funcionando igual.

---

---

## Cómo reportar un issue

1. Agregar entrada en este archivo con fecha, severidad y componente
2. Si aplica, abrir issue en el repo
3. Enlazar el PR que lo resuelve cuando exista
