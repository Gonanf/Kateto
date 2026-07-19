# Problemas Conocidos (Known Issues)

> Fecha: Noviembre 2026 · Compilado durante análisis post-MVP

---

## 1. whisper-server: `--device 1` no usa GPU correctamente

**Severidad:** Media
**Componente:** `providers/whisper.py` / servidor whisper.cpp externo

La flag `--device 1` no selecciona la GPU Vulkan correcta. En sistemas con múltiples GPUs (p.ej. Intel Iris Xe + AMD Radeon RX 6500 XT), whisper.cpp ignora el device index y usa la GPU por defecto o cae a CPU.

**Impacto:** Inferencia de whisper en CPU (~1.4 t/s) en vez de GPU. Latencia alta en el pipeline de transcripción.

**Causa:** bug conocido en whisper.cpp donde el device index no se mapea correctamente al backend Vulkan cuando hay GPUs integrada + discreta.

**Posible solución:** Forzar device mediante variable de entorno `GGML_VULKAN_DEVICE=1` o configurar `--no-gpu` y usar CPU con más threads. En producción, considerar migrar a un solo dispositivo GPU.

---

## 2. Sin tests end-to-end

**Severidad:** Media
**Componente:** `kateto/tests/`

Actualmente hay **33 archivos de test**, todos unitarios o con fixtures/mocks. Ningún test verifica el pipeline completo:

```
audio in → VAD → whisper → classifier → LLM → TTS → audio out
```

**Impacto:** El código que integra los componentes (especialmente `live.py` y `run_mode.py`) no tiene cobertura. Regresiones en integración real no se detectan hasta ejecución manual.

**Causa:** El MVP se construyó con Codex priorizando features sobre infraestructura de test. Los tests existentes se generaron para módulos específicos (event bus, plugin manager, VAD, backlog).

**Posible solución:** Agregar tests de integración que:
1. Inicien servidores mock de whisper/zonos/LLM
2. Ejecuten escenarios completos (transcripción → clasificación → generación → TTS)
3. Verifiquen tiempos de respuesta y eventos emitidos

---

## 3. CallbackQueue con capacity fijo en 32 — ✅ RESUELTO

**Severidad:** Baja (visible en condiciones de carga alta)
**Componente:** `kateto/plugins/audio_input/base.py`

La clase `CallbackQueue` tiene un `capacity=32` hardcodeado. No es configurable desde `config.toml` ni desde `PluginSettings`.

```python
self._callback_queue = CallbackQueue(capacity=32)
```

**Impacto:** En ráfagas largas de audio o cuando el pipeline de procesamiento está congestionado, se dropean frames de audio (`dropped_frames` se incrementa pero no hay notificación). El audio se corta sin que el usuario lo sepa.

**Causa:** decisión de diseño inicial para límite de memoria. No se expuso como parámetro de configuración.

**Solución aplicada:** Se agregó `callback_queue_capacity` en `PluginSettings` (config.py), `AudioInputConfig` (base.py), y se usa en `listener.py` en vez del hardcode 32.

---

## 4. Plugins sin isolation de errores (sin circuit breaker) — ✅ RESUELTO

**Severidad:** Alta
**Componente:** `kateto/core/manager.py` / `kateto/core/plugin.py`

Cuando un handler de evento lanza una excepción, el error se propaga al `emit()` y puede cancelar otros handlers en el mismo dispatch. No hay:
- Mecanismo de circuit breaker
- Aislamiento de failures por plugin
- Estado degradado (un plugin falla, los otros siguen)

**Impacto:** Un solo plugin buggy puede tumbar el event bus completo o silenciar errores. El sistema no tiene manera de "desconectar" un plugin que falla repetidamente.

**Causa:** El dispatch de eventos en `manager.py` usa `gather()` o tareas concurrentes sin manejo granular de errores por handler. El MVP priorizó simplicidad sobre resiliencia.

**Solución aplicada:**
1. Cada handler en `_run()` se ejecuta en try/except individual (ya existía desde el MVP)
2. `_consecutive_failures` se resetea a 0 en éxito, se incrementa en error
3. Al llegar a 5 fallos consecutivos, `_auto_disable_plugin()` deshabilita el plugin y emite `PluginErrorData` con `error_type="TooManyFailures"`
4. Fallos aislados (< 5) siguen reportándose normalmente

---

## 5. Sin logging estructurado — ✅ RESUELTO

**Severidad:** Media
**Componente:** `kateto/voices/base.py`, `kateto/providers/zonos.py`

El proyecto usa `print()` para salida de depuración y errores. No hay:
- Logger configurable por módulo
- Niveles (DEBUG, INFO, WARNING, ERROR)
- Formato estructurado (JSON o timestamp + módulo + nivel)
- Manejo de logs para producción

**Impacto:** Dificultad para debuggear issues en producción, especialmente en un sistema multi-agente con eventos asíncronos. No hay trazabilidad de qué eventos se emitieron, qué plugins respondieron, ni dónde falló el pipeline.

**Causa:** El MVP se construyó rápido con Codex, y `print()` es el camino más corto. No se diseñó un sistema de logging desde el inicio.

**Solución aplicada:** Se reemplazaron las escrituras a `/tmp/kateto_voice_debug.txt` con `logging.getLogger(__name__).debug()` en `voices/base.py` y `providers/zonos.py`. Los `print()` en `__main__.py` se mantienen (son apropiados para CLI).

---

## 6. Hot-reload sin test coverage — ✅ RESUELTO

**Severidad:** Media
**Componente:** `kateto/core/hot_reload.py`, `kateto/tests/`

El sistema de hot-reload (`HotReloadController`) es una pieza crítica: permite reemplazar plugins en caliente mientras el bus de eventos sigue corriendo. Sin embargo:

- **No tiene tests unitarios**
- **No tiene tests de integración** (reemplazar un plugin y verificar que los eventos se sigan emitiendo)
- Cualquier cambio en `manager.py` o `plugin.py` puede romper hot-reload sin que los tests lo detecten

**Impacto:** El TUI con hot-reload (feature clave del MVP) puede romperse silenciosamente. Regresiones en hot-reload no se detectan hasta ejecución manual.

**Causa:** hot-reload se agregó tarde en el desarrollo como feature de polish. Los tests existentes se escribieron antes.

**Solución aplicada:** Se agregaron 3 tests unitarios que cubren:
1. Reemplazo de plugin via `ReplacementFactory`
2. Observers se mantienen después del reemplazo
3. Eventos llegan al plugin reemplazado

Tests: `test_hot_reload_replaces_plugin_via_replacement_factory`, `test_hot_reload_preserves_observers_after_replacement`, `test_hot_reload_replaced_plugin_receives_events`

---

## 7. Proyecto no runneable sin configuración externa

**Severidad:** Alta (para nuevos desarrolladores)
**Componente:** `README.md`, `config/defaults/config.toml`

El sistema requiere servidores externos funcionando (whisper.cpp, zonos.cpp, llama.cpp) y no hay:
- `docker-compose.yml` para levantar todo
- Scripts de setup automático
- Modo "offline" con modelos mock para desarrollo
- Validación temprana de conectividad al iniciar

**Impacto:** Un nuevo desarrollador no puede ejecutar `kateto live` sin primero configurar manualmente 3 servidores de inferencia. La fricción de onboarding es alta.

**Causa:** El MVP asume que el desarrollador ya tiene los servidores corriendo (entorno existente del creador). No se diseñó para portabilidad.

**Posible solución:**
1. Agregar `kateto doctor` que verifique conectividad con cada servidor
2. Agregar modo demo (sin servidores reales, respuestas sintéticas)
3. Documentar en README los comandos exactos para iniciar cada servidor
4. Docker compose como opción

---

## 8. Audio capture bloquea el event loop asyncio (timeout en LLM calls) — ✅ RESUELTO

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_input/listener.py`

Cuando `audio_input_mic` está habilitado, su task de captura de audio ejecuta un loop bloqueante en el mismo event loop asyncio que usa el openai client para las llamadas HTTP al LLM. Esto impide que el client reciba la respuesta del modelo, causando timeouts silenciosos.

**Reproducción:**
1. Iniciar kateto con `audio_input_mic` habilitado (config default)
2. Enviar un evento `generate` a jane
3. El LLM nunca responde — timeout a los 30-60s
4. Sin `audio_input_mic`, la misma llamada funciona en ~2s

**Evidencia:**
```
# Con audio_input_mic habilitado:
AGENT_LOOP START: 4 messages, 19 tools
AGENT_LOOP iteration 0: calling LLM
TIMEOUT  # nunca llega respuesta

# Sin audio_input_mic (disabled):
Calling with 19 tools...
Done: '¡Hola! ¿En qué puedo ayudarle hoy?'  # funciona en ~2s
```

**Causa:** El plugin `audio_input_mic` crea un task (`kateto-audio-capture-audio_input_mic`) que ejecuta un loop de captura de audio continuo. La llamada a `self._vad.is_speech(samples)` (Silero VAD inference con PyTorch) es CPU-intensive y bloquea el event loop, impidiendo que las respuestas HTTP del openai client se procesen.

**Impacto:** El sistema completo queda inutilizable cuando el micrófono está activo — las voces no pueden generar respuestas. Solo funciona en modo "sin audio" (sin plugins de input).

**Solución aplicada:** Se movió `self._vad.is_speech(samples)` a un thread separado via `asyncio.to_thread()` en `listener.py:_drain_callback_queue()`. La inferencia de VAD ya no bloquea el event loop.

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

### 8. Audio capture bloquea el event loop asyncio (timeout en LLM calls) — ✅ RESUELTO

**Fix:** Se movió la llamada a `self._vad.is_speech(samples)` (Silero VAD inference) a un thread separado usando `asyncio.to_thread()`. Esto evita que la inferencia de PyTorch (CPU-intensive) bloquee el event loop principal donde se procesan las respuestas HTTP del openai client.

**Cambio en `_drain_callback_queue`:** `speech = await to_thread(self._vad.is_speech, samples)`

**Archivos:** `kateto/plugins/audio_input/listener.py`

**Evidencia:** El event loop ya no es bloqueado por VAD inference. Las llamadas HTTP al LLM pueden recibir respuestas aunque el micrófono esté activo.

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
