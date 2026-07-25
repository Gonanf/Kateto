# 🐱 Kateto — SPEC: Runtime Assembly (`run_mode.py`)

**Objetivo:** `run_mode.py` debe arrancar el runtime SIN importar ni conocer
ningún plugin por nombre. Hoy el ensamblado es hardcodeado; este SPEC lo
vuelve declarativo por descubrimiento.

---

## Estado actual (lo que hay que cambiar)

`kateto/run_mode.py` hoy importa por nombre y ensambla a mano:

```python
from kateto.core.workflow_engine import WorkflowEngine
from kateto.plugins.system.external_mcp import ExternalMcpManager
from kateto.plugins.system.mcp_server import McpEventServer, McpServerOptions
from kateto.plugins.system.voice_manager import VoiceManager
from kateto.plugins.system.http_server import HttpServer
from kateto.plugins.connector.calendar import ... build_google_calendar_connector
from kateto.voices.factory import create_voice
```

El `RuntimeOwner` instancia `VoiceManager`, `WorkflowEngine`, el calendar y
`HttpServer` explícitamente (run_mode.py:136-140, 268-269). Cualquier cambio
en el set de plugins exige tocar `run_mode.py`. Eso viola el principio de
extensionabilidad por evento (filosofía P4) y acopla el bootstrap al core.

**Ya hecho (no tocar):** `RuntimeOwner` ya NO hereda de `TuiConfigurationRuntime`
(se desacopló la TUI en SPEC_2). Eso queda.

---

## Objetivo

`run_mode.py` debe:

1. **No importar ningún plugin concreto.** Ni `VoiceManager`, ni `WorkflowEngine`,
   ni `HttpServer`, ni `ExternalMcpManager`, ni `McpEventServer`, ni calendar.
2. Arrancar el `PluginManager` y dejar que el **descubrimiento** resuelva qué
   plugins existen. Ya existe `kateto/core/discovery.py` (`discover_plugins`) y
   `build_event_runtime` en `live.py` que descubre por directorio/config.
3. Los plugins "core" (VoiceManager, WorkflowEngine, HttpServer, MCP servers,
   calendar) deben auto-registrarse vía el mismo mecanismo que los plugins de
   `kateto/plugins/` — no por import explícito en `run_mode.py`.

---

## Diseño propuesto

### Mecanismo de registro
Los plugins se registran a sí mismos en un registro central (ej. un
`PluginRegistry` en `core/`) en el momento del import del módulo, o vía entry
points. `run_mode.py` solo hace:

```python
manager = PluginManager()
discovered = discover_plugins(config)        # escanea plugins/ + voices/ + system/
for plugin in discovered:
    await manager.enable_plugin(plugin)
```

Y los plugins core (VoiceManager, WorkflowEngine, HttpServer) pasan a vivir
bajo `kateto/plugins/system/` o un `kateto/plugins/core/` descubrible, en vez
de ser instanciados a mano en `run_mode.py`.

### Qué queda en `run_mode.py` (mínimo)
- `RuntimeOwner`: orquesta start/stop del `PluginManager`, no de plugins.
- `build_runtime_owner`: ensambla el manager + discovery, SIN nombres de plugin.
- `run_event_runtime`: entrypoint de arranque.
- Hooks de lifecycle (`on_voice_enable`) → pueden moverse a un plugin de sistema
  o quedar como callback del manager, pero SIN importar `create_voice` por nombre
  (el discovery ya trae las voces).

### `shared` / dependencias
Hoy `run_mode.py:260` pasa `external_mcp_manager` por un dict `shared` global.
Eso puede quedar (es el mecanismo de `build_event_runtime`), pero `run_mode.py`
no debe importar `ExternalMcpManager` para crearlo — el plugin se auto-registra
y lo expone vía el manager.

---

## Reglas de filosofía (§4f del SPEC_2, aún vigentes)
- **P4 Útil / extensible:** agregar un plugin no debe requerir tocar `run_mode.py`.
- **P6 Reactivo:** sin I/O bloqueante en el bootstrap; todo `async`.
- **Anti-duplicación (P6):** una sola fuente de inferencia/tooling, no 2 plugins
  que hagan lo mismo con backends distintos.
- **Ponytail:** el `RuntimeOwner` no debe mutar atributos privados de plugins
  (el hack de `_extra_tools`/`_tools` en `VoiceAgent` va a un método público
  `add_tools()`).

---

## Fuera de alcance
- El dashboard Nuxt (ya tiene su propio SPEC en `OpenaiBuildWeek/Dashboard`).
- Los plugins futuros de `docs/features/future-plugins.md`.

---

## Criterio de done
- `run_mode.py` no contiene ningún `from kateto.plugins... import <PluginConcreto>`
  ni `from kateto.core.workflow_engine import WorkflowEngine`.
- Agregar un plugin nuevo = crear archivo en `kateto/plugins/...`, sin tocar
  `run_mode.py`.
- `uv run pytest` pasa (sin collection errors de `space`, `kateto.qa`, `scripts`).
