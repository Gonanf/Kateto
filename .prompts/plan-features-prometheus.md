# PROMPT PARA PROMETHEUS — Plan de features Kateto

Sos Prometheus (agente de planificación de OMO). Tu trabajo es ANALIZAR el repo y PRODUCIR UN PLAN de implementación. NO escribas código. Generá un plan estructurado, con archivos a tocar, orden de dependencias, y riesgos. El plan debe ser accionable por Hephaestus después.

## Repositorio
`/home/chaos/proyectos/OpenaiBuildWeek/Kateto/` — proyecto Python `kateto` (event-driven voice team). Stack: Python 3.12+, uv, pytest-asyncio, Pydantic, Textual 8, MCP 1.28.

## CONTEXTO VERIFICADO EN EL CÓDIGO (lee los archivos reales, no el AGENTS.md que está desactualizado)
- `kateto/core/event.py` — `EventModel` base (frozen, strict). `register_event(name, contract)`, `emit(name, data)` valida tipo.
- `kateto/core/manager.py` — `PluginManager` (singleton): bus de eventos + lifecycle. Cada plugin tiene su `asyncio.Queue`. Filtros: Broadcast, Target, Capabilities (AND), Only Once. Self-delivery OFF.
- `kateto/core/plugin.py` — `Plugin` base. `iter_event_handlers()` auto-escanea métodos `on_*`. Routing por target/capabilities/only_once.
- `kateto/core/config.py` — `KatetoSettings` con flag `hot_reload: bool = False` que NADIE usa.
- `kateto/core/hot_reload.py` — NO EXISTE en disco (AGENTS.md miente). Hay que construirlo.
- `kateto/voices/factory.py` — `VoiceProfile` (voice_id, display_name, role, system_prompt). `create_voice()`.
- `kateto/voices/base.py` — `VoiceAgent` (profile, memory, generation).
- `kateto/voices/memory.py` — `VoiceMemory` (write_soul, read_soul, append_journal).
- `kateto/voices/tools.py` — `VoiceToolExecutor`.
- `kateto/plugins/voice_soul_manager/__init__.py` + `updater.py` — `VoiceSOULManager(Plugin)` escucha `voice_idle` y escribe SOUL/JOURNAL vía `VoiceMemory` SIN validación ni snapshot. ES LA BOMBA A ENVOLVER.
- `kateto/plugins/system/` — TUI (Textual) + internal MCP server.

## FEATURES A PLANIFICAR (de ~/proyectos/Blogs/kateto-features-para-opencode.md)

### 0. Hallazgos previos
- No existe HotReloadController real.
- voice_soul_manager muta sin red de seguridad.

### 1. Scheduling layer (cron para plugins y agentes)
- Timer como ciudadano del bus: plugin/agente emite `ScheduleRequest` (delay/cron/interval/jitter); un `SchedulerPlugin` dispara el evento cuando toca. El agente no duerme.
- Casos: ejecutor aleatorio (voz al azar en rango aleatorio habla), mutación automática de estado, "vuelvo a hablar en 15 min".
- Soportar one-shot, interval, cron, jitter aleatorio. Guardraíles: no 24/7, no si ya habla, horas muertas.
- Libs a evaluar: APScheduler (AsyncIOScheduler), rocketry, croniter. O adaptador a Hermes cron.

### 2. Fusión Kateto + Hermes
- Hermes = orquestación (cron/skills/memoria). Kateto = voz/realtime.
- Bridge: Kateto expone bus como provider para Hermes. Para provider Hermes: tool-management off + cronjob-MCP deshabilitado para agentes.

### 3. Agent tool: cron job
- Tool vía VoiceToolExecutor que emite ScheduleRequest. Deshabilitado para provider Hermes.

### 4. Plugin opcional: cron job capability
- Marker/capability que SchedulerPlugin descubre, o plugin emite ScheduleRequest en enable().

### 5/7. Mutación segura de SOUL/workflow/memory (envolver voice_soul_manager)
- Antes de escribir: snapshot. Validar con Pydantic. Rollback en caliente si live-parse del prompt falla.
- Store de snapshots con versionado nativo: **Event Sourcing (`eventsourcing`) para log debug/auditoría** + **ZODB para undo**. SQLite solo fallback.
- Envolver write_soul/write_journal de VoiceMemory.

### 6. Hot Reload NUEVO
- watcher detecta cambio → cancel plugin task → importlib.reload(módulo) → recrear plugin → re-enable. Usar `PluginManager.replace_plugin` (ya existe).
- Lib recomendada: `watchfiles` (Rust, autor de pydantic). Alternativa: hupper.

### 7. Memoria de 3 niveles (vectorial largo plazo)
- Corto = deque de eventos en PluginManager._events.
- Mediano = MEMORY.md + VoiceMemory.
- Largo = DB vectorial como SinkPlugin (escucha transcription/text_chunk/generate/voice_idle). ChromaDB para arrancar, LanceDB si crece. Embeddings locales o OpenAI.

### 8. Static Vision plugin
- Captura frame en rango aleatorio (jitter), emite `VisionFrame`. Agente lo toma por event queue.
- Libs: mss (captura), python-ewmh/python-xlib (recorte por PID X11), Pillow. Wayland: grim+slurp. VLM para describir.
- Contract: VisionFrame(frame, source_pid, ts, dept="fun").

### 9. Process Audio Whisper plugin
- Transcribe audio de salida de un proceso (por PID), emite `ProcessTranscription`.
- Reusa STT Whisper existente. Libs: pulsectl (null sink+loopback PulseAudio) o pw-record (PipeWire).

### 10. Departamentos (filtro de enrutamiento real)
- `dept` es campo de PRIMER NIVEL en EventEnvelope (no solo metadata). Bus filtra por depts del voice.
- VisionFrame/ProcessTranscription llevan dept="fun". Gestión no los ve.
- Config por voz: VoiceProfile.depts: list[str]. Default global default_voice_dept (sugerido "fun"). Override en config.toml [voice.<name>] dept/depts.
- Roles: Jane=fun (coms/razón en streams, contrapeso de Whisperer también fun), Doktor=management (PM), Conquest=management (Scrum master/tech lead), Whisperer=fun.
- Fuente Doktor/Conquest: ~/Documentos/gestion de proyectos/anotaciones/ (cursos Coursera, templates).

### 11. TTS provider Boson.ai
- Nuevo provider en audio_output, selector por voz (tts_provider="boson").
- Debe inyectar prompt con instrucciones/acciones/ejemplos a agentes que lo necesiten, filtrado por dept="fun".
- get_agent_prompt_block() -> str. No es fine-tuning, es prompt-engineering.

### 12. Visual overlay (Veadotube Mini)
- Plugin visual_overlay escucha generate/text_chunk/estado de habla. Frontend web: fondo transparente, subtítulos, PNG partido en 2 capas (parte superior + boca) con bobbing tipo títere.
- Software de kokonuts = Veadotube Mini (overlay transparente, 2 estados boca, OBS). Integrar (puente) vs reimplementar.
- Transporte: WebSocket/SSE (reusar MCP server de system/). Audio→visema: pydub/librosa.

## QUÉ ENTREGAR (plan, no código)
1. Para cada feature: archivos a crear/modificar, orden de implementación, dependencias entre features.
2. Secuencia recomendada (qué va primero: ej. departamentos y envolver voice_soul_manager son base; scheduling habilita 8/9; etc.).
3. Riesgos y puntos ciegos (p.ej. X11 vs Wayland, compat APScheduler asyncio 3.12, Veadotube integración).
4. Lista de decisiones que el humano debe tomar (ya marcadas como "pendiente" en el doc).
5. Si falta leer algún archivo del repo para planificar bien, hacelo y citálo.

Formato: markdown con secciones por feature + un roadmap ordenado. No escribas código, solo el plan.
