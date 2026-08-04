# 🐱 Kateto — SPEC (arquitectura)

SPEC de arquitectura del sistema Kateto. Las features futuras (plugins de TTS
boson.ai, PNGTuber, etc.) viven en `docs/features/future-plugins.md`. Los bugs
en `docs/bugs/`.

---

## 0. Visión: Kateto como empresa

Kateto se modela como una **empresa**. La empresa tiene **departamentos**
(Gestión de Proyectos, Desarrollo de Software, Diseño Gráfico, Marketing, Legal,
Contable, …). Cada departamento tiene **voces**; cada voz tiene un rol/tarea
dentro del departamento. Ejemplo del Departamento de Gestión de Proyectos:
- **Jane** — comunicación con clientes y demás departamentos.
- **Doktor** — planes de comunicación, portafolio de proyecto, propuesta, WBS,
  análisis de riesgos, etc.
- **Conquest** — reuniones y seguimiento de metodología (Scrum, Lean, Lean Six
  Sigma, Waterfall, u otra); envía progresos a Doktor.

Cada departamento tiene eventos / plugins que emiten eventos; las voces deciden
a qué responder. Doktor puede anotar "hay reuniones los martes"; el martes, un
**ejecutor** dispara a Conquest para correr la reunión por sí solo.

**Objetivos:**
1. **Focalizar la información** — a LLMs pequeños/locales, meter todo el
   contexto en un solo agente obliga a comprimir y baja la calidad. Los
   departamentos acotan lo que cada voz debe saber.
2. **Proactivo, no solo reactivo** — el sistema es un **bus de eventos** (no un
   grafo cableado tipo LangGraph): cualquier nodo (input de usuario, cron,
   workflow, otro agente/programa) es emisor y suscriptor; los nodos se ejecutan
   solos al recibir sus eventos. El "grafo" es la *visualización* (dashboard),
   no la estructura de código.
3. **Eficiente** — además de MCPs y Skills, hay **Workflows** para actividad
   determinística (mismo comando sin variación, o pasos sin LLM). Son funcionales
   (inician/terminan sin human-in-the-loop, con checkpoints de verificación
   automática) y eficientes (no llaman a un LLM cuando no hace falta).
4. **Agradable/Divertido** — formal cuando se necesita, divertido para marketing.
   Las interrupciones sirven de recurso cómico o de adversarial entre 2 IAs
   (mejor solución por múltiples perspectivas; requiere un árbitro que cierre el
   debate).

---

## 1. Eliminar conexiones a Google
- **Estado:** ✅ HECHO (2026-08-04).
- Se eliminan los conectores `connector_calendar` (Google Calendar) y cualquier
  integración Google Meet/YouTube OAuth del runtime.
- `build_google_calendar_connector` y sus imports en `run_mode.py` se borran.
- Razón: requieren OAuth no testeado, no aportan al loop de voz y añaden
  superficie de ataque + dependencias. El "YouTube Live Chat listener" futuro
  (docs/features) se replantea sin acoplar OAuth de Google al core.
- El `CalendarFailure` y el factory en `RuntimeDependencies` se eliminan.
- **Realizado:** borrado `kateto/plugins/connector/calendar.py` y
  `kateto/tests/test_calendar.py`; removido el wiring de `run_mode.py`
  (imports, `calendar_factory` en `RuntimeDependencies`, helper
  `_configured_calendar`, `LiveAssemblyConfigurationError`); removida la
  dependencia `google-auth-oauthlib` de `pyproject.toml` + `uv.lock`;
  ajustados `kateto/tests/test_run_orchestration.py` (sin calendar factory) y
  los docs (`docs/plugins/connectors.md`, `docs/architecture/design-decisions.md`,
  `docs/development/tooling.md`). Suite completa: 153 passed.

---

## 2. CLI con Cliff (openstack/cliff)
- **Estado:** ✅ HECHO (2026-08-04).
- **Ref:** https://github.com/openstack/cliff — framework de CLI basado en
  `argparse` + `stevedore` (plugins de comandos). Cada comando es una clase
  `Command` con `get_parser()` + `take_action()`.
- Hoy `__main__.py` usa un `match` hardcodeado de `sys.argv` (`config check`,
  `run`, `tui`, `smoke`). Se reemplaza por una app Cliff:
  `commandmanager = app.CommandManager('kateto.cli')` que descubre comandos.
- **Plugins añaden comandos:** cada plugin registra su comando vía stevedore
  (entry point `kateto.cli` o un registry interno). Un plugin declara su
  comando como subclase de `cliff.command.Command` y Cliff lo expone como
  subcomando (`kateto <plugin-cmd> ...`) sin tocar el core (filosofía P4).
- **Comandos core migrados a Cliff:** `config check`, `run`, `tui`, `smoke`
  pasan a ser clases `Command` propias del command manager.
- Dependencias: agregar `cliff` (+ `stevedore`, `prettytable` si se usa tabla)
  al `pyproject.toml`. Mantener `uv`.
- `__main__.py` queda como thin entrypoint que instancia la app Cliff y corre
  `run(argv)`.
- **Realizado:** nuevo paquete `kateto/cli/` — `registry.py` (registro interno
  `register_command()`/`all_commands()`, la opción "registry interno" del SPEC,
  sin entry points stevedore), `commands.py` (`ConfigCheck`, `Run`, `Smoke`,
  `Tui` como subclases de `cliff.command.Command`, con `--fixture` en
  `Smoke`/`Tui` y manejo de errores de config → exit 2), `app.py`
  (`KatetoCommandManager` que carga del registry + `KatetoApp(App)` con
  `deferred_help=True`). `kateto/__main__.py` es ahora un thin entrypoint
  (`main()` → `KatetoApp().run(argv)`, sin argv → help, exit 0). Se añadió
  `cliff==4.15.0` a `pyproject.toml` + `uv.lock`. `kateto/tests/test_cli_live.py`
  actualizado (help expone `run`/`config check`; dispatch de `run`
  monkeypatchea `kateto.cli.commands`). Suite completa: 153 passed.

---

## 3. Logging con loguru, visible en `kateto run`
- **Estado:** ✅ HECHO (2026-08-04).
- Migrar de `logging` estándar a **loguru** en todo el codebase.
- Configurar logger de loguru al arrancar el runtime (`run_event_runtime` /
  `RuntimeOwner.start`) con salida a consola (y opcionalmente archivo en el
  config dir).
- `kateto run` debe mostrar los logs en vivo (nivel configurable por
  `config.toml`, default INFO).
- Los errores por plugin (ej. bug 38 de Doktor) deben verse claros en el log,
  con plugin/evento/origen.
- Reemplazar `import logging` + `logging.getLogger(...)` por
  `from loguru import logger` en todos los módulos.
- **Realizado:** dependencia `loguru` añadida a `pyproject.toml` + `uv.lock`.
  Los 8 módulos con `import logging` (`core/manager.py`, `voices/base.py`,
  `providers/zonos.py`, `providers/edgetts.py`, `providers/camb.py`,
  `plugins/system/http_server.py`, `plugins/system/voice_manager.py`,
  `plugins/system/external_mcp.py`) migrados a `from loguru import logger`
  (alias `log = logger`) con formatos `%s`/`%r`/`%d` → `{}`. Nuevo
  `_configure_logging()` en `run_mode.py` (sink stderr, nivel configurable) y
  campo `kateto.log_level` (default `INFO`) en `KatetoSettings` +
  `config/defaults/config.toml`. Verificado: `kateto run` muestra
  `HTTP server started on 127.0.0.1:8080` vía loguru (INFO). Suite completa:
  153 passed.

---

## 4. `run_mode.py` sin dependencias de plugins (desacoplar bootstrap)
- **Estado:** ✅ HECHO (2026-08-04).
**Objetivo:** `run_mode.py` debe arrancar el runtime SIN importar ni conocer
ningún plugin por nombre. Hoy el ensamblado es hardcodeado; se vuelve
declarativo por descubrimiento.

### Estado actual (lo que hay que cambiar)
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
`HttpServer` explícitamente. Cualquier cambio en el set de plugins exige tocar
`run_mode.py`. Eso viola el principio de extensionabilidad por evento (P4) y
acopla el bootstrap al core.

**Ya hecho (no tocar):** `RuntimeOwner` ya NO hereda de `TuiConfigurationRuntime`
(se desacopló la TUI). Eso queda.

### Objetivo
`run_mode.py` debe:
1. **No importar ningún plugin concreto** (ni `VoiceManager`, ni
   `WorkflowEngine`, ni `HttpServer`, ni `ExternalMcpManager`, ni
   `McpEventServer`, ni calendar).
2. Arrancar el `PluginManager` y dejar que el **descubrimiento** resuelva qué
   plugins existen (`discover_plugins` en `core/discovery.py`, usado por
   `build_event_runtime` en `live.py`).
3. Los plugins "core" (VoiceManager, WorkflowEngine, HttpServer, MCP servers,
   calendar) se auto-registran vía el mismo mecanismo que los plugins de
   `kateto/plugins/`, no por import explícito en `run_mode.py`.

### Diseño propuesto
- **Mecanismo de registro:** los plugins se registran a sí mismos en un registro
  central (`PluginRegistry` en `core/`) al importarse, o vía entry points.
  `run_mode.py` solo hace:
  ```python
  manager = PluginManager()
  discovered = discover_plugins(config)
  for plugin in discovered:
      await manager.enable_plugin(plugin)
  ```
  Los plugins core (VoiceManager, WorkflowEngine, HttpServer) viven bajo
  `kateto/plugins/system/` o `kateto/plugins/core/` descubrible, en vez de
  instanciarse a mano en `run_mode.py`.
- **Qué queda en `run_mode.py` (mínimo):** `RuntimeOwner` orquesta start/stop
  del `PluginManager` (no de plugins). `build_runtime_owner` ensambla manager +
  discovery sin nombres de plugin. `run_event_runtime` es el entrypoint. Los
  hooks de lifecycle (`on_voice_enable`) pueden moverse a un plugin de sistema o
  quedar como callback del manager, pero SIN importar `create_voice` por nombre.
- **`shared` / dependencias:** `run_mode.py:260` pasa `external_mcp_manager` por
  un dict `shared` global. Eso puede quedar (es el mecanismo de
  `build_event_runtime`), pero `run_mode.py` no debe importar `ExternalMcpManager`
  para crearlo — el plugin se auto-registra y lo expone vía el manager.

### Reglas de filosofía (§4f del SPEC_2, aún vigentes)
- **P4 Útil/extensible:** agregar un plugin no debe requerir tocar `run_mode.py`.
- **P6 Reactivo:** sin I/O bloqueante en el bootstrap; todo `async`.
- **Anti-duplicación (P6):** una sola fuente de inferencia/tooling.
- **Ponytail:** `RuntimeOwner` no debe mutar atributos privados de plugins (el
  hack de `_extra_tools`/`_tools` en `VoiceAgent` va a un método público
  `add_tools()`).

### Criterio de done (run_mode)
- ✅ `run_mode.py` no importa ni instancia ningún plugin concreto en runtime:
  los únicos imports a `kateto.plugins.*` quedan bajo `if TYPE_CHECKING:` y solo
  anotan los campos de `RuntimeComponents`/propiedades (no se ejecutan ni
  acoplan el ensamblado). Sin `from kateto.core.workflow_engine import WorkflowEngine`:
  la propiedad `workflow_engine` resuelve por nombre
  (`plugin.name == "workflow_engine"`).
- ✅ Agregar un plugin = crear archivo en `kateto/plugins/...` (o su
  `create_plugins(ctx)`), sin tocar `run_mode.py`.
- **Realizado (2026-08-04):** nuevo `kateto/plugins/system/__init__.py` con
  `create_plugins(ctx)` — el factory que `_scan_plugins` ya invocaba — construye
  los servicios no-plugin (ExternalMcpManager, McpEventServers internos,
  HttpServer config-gated) en `ctx.shared` y devuelve los plugins core siempre
  activos (`VoiceManager`, `WorkflowEngine`) para discovery. `kateto/live.py`
  crea el `PluginManager` ANTES de discovery y lo registra en
  `shared["manager"]`. `VoiceManager` es autónomo: eliminado el callback
  `on_voice_enable` de run_mode; el handler resuelve su `DiscoveryContext` vía
  `discovery_context_for((self,))` (import lazy de `create_voice` para compat
  con el monkeypatch de `test_run_orchestration`) y replica la lógica previa de
  voice_enabled/creación dinámica. `run_mode.py` sin imports de plugins en
  runtime: eliminados `ExternalMcpManager`, `McpEventServer`/`McpServerOptions`,
  `VoiceManager`, `HttpServer`, `WorkflowEngine` y `create_voice`;
  `RuntimeOwner.start()` deja de instanciar `VoiceManager`;
  `_authorized_mcp_servers` eliminado (los McpEventServers salen de
  `shared["mcp_servers"]`); `build_runtime_owner` lee
  mcp_servers/http_server/external_mcp de `shared`.
  `voices/factory.py`: `external_mcp = ctx.external_mcp or ctx.get_shared("external_mcp")`.
  Suite completa: 153 passed; `smoke --fixture`: 44 passed.

---

## Bugs relacionados
- **Bug 38** (`docs/bugs/38-doktor-generate-dict-conversation_id.md`): Doktor
  caía en `generate` con `'dict' object has no attribute 'conversation_id'`.
  ✅ RESUELTO (2026-08-04): causa raíz real = `_pydantic_agent_loop` pasaba
  dicts crudos de OpenAI como `message_history` de pydantic-ai (crash en
  `resolve_conversation_id` antes de cualquier HTTP). Fix: conversión a
  `ModelRequest`/`ModelResponse`; además se añadió `HermesProvider` que envía
  `conversation_id` en el body para el harness Hermes. Suite completa: 153 passed.

---

## Criterio de done global
- `uv run kateto run` no menciona Google; conectores Google eliminados y tests
  ajustados.
- CLI migrado a Cliff (openstack/cliff); los plugins registran comandos vía
  stevedore sin tocar el core. `kateto run|tui|config check|smoke` funcionan
  como comandos Cliff.
- `uv run kateto run` muestra logs vía loguru en consola; bug 38 resuelto y
  visible en log si recurre.
- `run_mode.py` no importa plugins por nombre; nuevos plugins no lo tocan.
