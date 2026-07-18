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

## 3. CallbackQueue con capacity fijo en 32

**Severidad:** Baja (visible en condiciones de carga alta)
**Componente:** `kateto/plugins/audio_input/base.py`

La clase `CallbackQueue` tiene un `capacity=32` hardcodeado. No es configurable desde `config.toml` ni desde `PluginSettings`.

```python
self._callback_queue = CallbackQueue(capacity=32)
```

**Impacto:** En ráfagas largas de audio o cuando el pipeline de procesamiento está congestionado, se dropean frames de audio (`dropped_frames` se incrementa pero no hay notificación). El audio se corta sin que el usuario lo sepa.

**Causa:** decisión de diseño inicial para límite de memoria. No se expuso como parámetro de configuración.

**Posible solución:** Exponer `callback_queue_capacity` en `AudioInputConfig` (ya hay validación para `capacity` positiva en el constructor de `CallbackQueue`, solo falta conectar con la configuración).

---

## 4. Plugins sin isolation de errores (sin circuit breaker)

**Severidad:** Alta
**Componente:** `kateto/core/manager.py` (PluginManager.event dispatch)

Cuando un handler de evento lanza una excepción, el error se propaga al `emit()` y puede cancelar otros handlers en el mismo dispatch. No hay:
- Mecanismo de circuit breaker
- Aislamiento de failures por plugin
- Estado degradado (un plugin falla, los otros siguen)

**Impacto:** Un solo plugin buggy puede tumbar el event bus completo o silenciar errores. El sistema no tiene manera de "desconectar" un plugin que falla repetidamente.

**Causa:** El dispatch de eventos en `manager.py` usa `gather()` o tareas concurrentes sin manejo granular de errores por handler. El MVP priorizó simplicidad sobre resiliencia.

**Posible solución:**
1. Envolver cada handler en un try/except individual
2. Agregar contador de fallos por plugin con umbral de desactivación automática
3. Emitir evento `plugin_error` con metadata del error
4. Implementar PluginManager.deactivate_plugin() para aislamiento

---

## 5. Sin logging estructurado

**Severidad:** Media
**Componente:** Todo el proyecto

El proyecto usa `print()` para salida de depuración y errores. No hay:
- Logger configurable por módulo
- Niveles (DEBUG, INFO, WARNING, ERROR)
- Formato estructurado (JSON o timestamp + módulo + nivel)
- Manejo de logs para producción

**Impacto:** Dificultad para debuggear issues en producción, especialmente en un sistema multi-agente con eventos asíncronos. No hay trazabilidad de qué eventos se emitieron, qué plugins respondieron, ni dónde falló el pipeline.

**Causa:** El MVP se construyó rápido con Codex, y `print()` es el camino más corto. No se diseñó un sistema de logging desde el inicio.

**Posible solución:** Agregar logger con `logging.getLogger(__name__)` en cada módulo, configurable desde `config.toml` (nivel por módulo, formato, output file).

---

## 6. Hot-reload sin test coverage

**Severidad:** Media
**Componente:** `kateto/core/hot_reload.py`, `kateto/tests/`

El sistema de hot-reload (`HotReloadController`) es una pieza crítica: permite reemplazar plugins en caliente mientras el bus de eventos sigue corriendo. Sin embargo:

- **No tiene tests unitarios**
- **No tiene tests de integración** (reemplazar un plugin y verificar que los eventos se sigan emitiendo)
- Cualquier cambio en `manager.py` o `plugin.py` puede romper hot-reload sin que los tests lo detecten

**Impacto:** El TUI con hot-reload (feature clave del MVP) puede romperse silenciosamente. Regresiones en hot-reload no se detectan hasta ejecución manual.

**Causa:** hot-reload se agregó tarde en el desarrollo como feature de polish. Los tests existentes se escribieron antes.

**Posible solución:** Agregar tests que:
1. Registren un plugin, lo enable/disable
2. Reemplacen el plugin vía ReplacementFactory
3. Verifiquen que los eventos nuevos lleguen al reemplazo
4. Verifiquen que los observers se mantengan

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

## 8. Audio capture bloquea el event loop asyncio (timeout en LLM calls)

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_input/base.py`, `kateto/voices/base.py`

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

**Causa:** El plugin `audio_input_mic` crea un task (`kateto-audio-capture-audio_input_mic`) que ejecuta un loop de captura de audio continuo. Este loop no hace `await` con frecuencia suficiente, o el backend de audio (PyAudio/PulseAudio) realiza operaciones bloqueantes que impiden que el event loop procese las respuestas HTTP pendientes del openai client.

**Impacto:** El sistema completo queda inutilizable cuando el micrófono está activo — las voces no pueden generar respuestas. Solo funciona en modo "sin audio" (sin plugins de input).

**Posible solución:**
1. Mover la captura de audio a un thread separado (usar `asyncio.to_thread()` o un executor)
2. Reducir el batch size del callback de audio para que el loop haga `await` con más frecuencia
3. Usar `loop.add_reader()` en vez de polling para la captura de audio
4. Agregar un flag `audio_enabled` que desactive la captura cuando se necesita generar texto (modo CLI/TUI sin micrófono)

---

## 9. List plugins response lost in text_chunk capture

**Severidad:** Baja
**Componente:** `kateto/voices/base.py`, `_emit_chunk`

Cuando Jane responde a un generate con una respuesta larga que incluye `\n` al inicio, el `_emit_chunk` emite un `text_chunk` event. Sin embargo, el chunk solo contiene el contenido de `response.text`, que puede estar vacío o tener solo `\n` cuando el modelo genera una respuesta de tool_call + texto combinado.

**Evidencia:**
```
AGENT_LOOP got response: text='\n' tool_calls=1
AGENT_LOOP got response: text='\nTodos los plugins están habilitados...' tool_calls=0
# Pero el text_chunk capturado está vacío
```

**Causa:** El modelo LLM (Kateto) genera reasoning tokens en `<think>` tags que no se incluyen en `response.text`. El texto visible solo aparece después del tool_call, pero el primer chunk puede estar vacío.

**Impacto:** Respuestas parcialmente perdidas en el TUI. No es un bug crítico pero afecta la experiencia.

---

## Issues resueltos / Cerrados

Actualmente ninguno.

---

## Cómo reportar un issue

1. Agregar entrada en este archivo con fecha, severidad y componente
2. Si aplica, abrir issue en el repo
3. Enlazar el PR que lo resuelve cuando exista
