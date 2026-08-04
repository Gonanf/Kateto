# PROMPT PARA HEPHAESTUS — Implementación de features Kateto

Sos Hephaestus (agente de implementación de OMO). Tenés el PLAN de prometheus (abajo) + decisiones del humano. IMPLEMENTÁ el código en el repo. Usá TDD (pytest-asyncio strict). No rompas lo existente.

## Repositorio
`/home/chaos/proyectos/OpenaiBuildWeek/Kateto/` — Python `kateto`, Python 3.12+, uv, Pydantic, Textual 8, MCP 1.28.

## DECISIONES DEL HUMANO (cierran dudas de prometheus)
- **R2 (snapshots/undo):** usar **ZODB para el undo** (object DB embebida, `undo()` transaccional nativo — guardás el objeto SOUL y rolls back) + **logs de eventos en una base de datos para debug** (todos los eventos/mutaciones van a una DB para replay/debug si hace falta). JSONL append-only queda como fallback si no se quiere ZODB. Event sourcing puro (`eventsourcing` lib) descartado como primario (arrastra SQLAlchemy).
- **R1 (scheduler):** **croniter + engine asyncio propio** (no APScheduler, issues asyncio 3.12). OK.
- **R7 (Boson.ai API, ya investigada):** `POST https://api.boson.ai/v1/audio/speech`, auth `Authorization: Bearer $BOSON_API_KEY`, body JSON `{model: "higgs-tts-3"|"higgs-audio-v3-tts", input, voice?, ref_audio?, ref_text?, stream?: bool, response_format?: "mp3"}`. Devuelve audio mp3. Streaming soportado. Voice cloning vía ref_audio/ref_text.

## PLAN DE PROMETHEUS (resumen ejecutivo, leé el repo para los detalles)

### M1 — Base (paralelo)
- **F10 Departamentos:** `dept: str|None=None` en `EventEnvelope` (event.py:302). `manager.emit(..., dept=...)`. `_resolve_subscribers` (manager.py:323) filtra: si `envelope.dept is not None` → solo plugins cuya `depts` incluya ese dept. Ortogonal a target/capabilities. `Plugin.depts: tuple[str,...]=()` (plugin.py:23). `default_voice_dept="fun"` en KatetoSettings; `dept`/`depts` en VoiceSettings (mutuamente excluyentes, casefold). `depts` en VoiceProfile; pasar a VoiceAgent. **Anti-spoofing:** si source es voz, validar que el dept pedido esté en sus depts → ValueError. Roles: jane=fun, doktor=management, conquest=management, default=fun.
- **F5 Safe soul:** `SoulSnapshotStore` backend pluggable (`ZodBackend` para undo + `JsonlAuditBackend` o DB de logs para debug). Envolver `write_soul`/`append_journal` en VoiceMemory (snapshot → validación Pydantic → write → registrar). Rollback en caliente en `VoiceAgent._messages_for` si falla parseo del soul.
- **F6 Hot Reload:** `HotReloadController` con `watchfiles` (debounce ~300ms) watch `kateto/plugins/*`, `kateto/voices/*`, config dirs. Cambio → `importlib.reload(package)` + limpiar sub-módulos de sys.modules → re-run `create_plugins(ctx)` → `manager.replace_plugin`. Arrancar tras enable, detener en close. Flag `hot_reload` (config.py:44) ya existe.

### M2 — Scheduling
- **F1 SchedulerPlugin:** contrato `ScheduleRequestData` (kind: one_shot|interval|cron|jitter; delay_s/interval_s/cron_expr/jitter_s:[min,max]; event_name; event_data:dict; target; dept; max_runs; voice_guard). Engine asyncio propio (croniter para cron). Al disparar: validar event_data vs `manager.get_event_contract(event_name)` y emit. Guardraíles: mapa voz→status (on_voice_status), no disparar si TALKING/THINKING, horas activas, tope disparos/hora. "Ejecutor aleatorio": elige voz fun al azar y emite `speak` con gag.
- **F3 Tool agenda:** tool builtin `schedule_event` en VoiceToolExecutor → emite schedule_request → job_id. Gate Hermes: `disable_scheduling_tools: bool` en executor; factory ruta conversation_id (HermesProvider) lo setea + no inyecta cronjob-MCP.
- **F4 Capability:** emit-in-enable (plugin emite su schedule_request en enable()), no marker class.

### M3 — Captura (depende M1+M2)
- **F8 Static Vision:** `VisionFrameData` (frame: bytes JPEG/PNG, source_pid:int|None, ts, dept="fun"). `StaticVisionPlugin` auto-programa jitter (30–90s) vía scheduler; captura (mss pantalla completa; X11 python-xlib por PID; Wayland grim/slurp) → emite vision_frame dept=fun. Sin VLM en v1.
- **F9 Process Audio Whisper:** `ProcessTranscriptionData` (text, source_pid, ts, dept="fun", language?). `ProcessAudioWhisperPlugin` auto-jitter; captura N segundos del audio de la app (PulseAudio pulsectl null sink+loopback, o PipeWire pw-record/pw-loopback) → transcribe reusando whisper → emite.

### M4 — Integración (paralelo tras M1/M2)
- **F7 Memoria vectorial:** `MemorySinkPlugin` suscrito a transcription/text_chunk/generate/voice_idle/tool_result → indexa ChromaDB (PersistentClient, config dir). Metadata voice/type/ts/trace_id/dept. `VoiceAgent._messages_for` inyecta top-k semánticos (timeout corto, fail→skip). Embeddings: reusar endpoint OpenAI-compatible del LLM si expone /embeddings, fallback sentence-transformers.
- **F2 Hermes:** `HermesProvider.manage_tools: bool=False` → no inyecta tools. Bridge v1 unidireccional (Hermes→Kateto). Bidireccional fuera de alcance.
- **F11 Boson TTS:** `BosonTTSProvider` HTTP (misma forma que zonos.py) + registro. `VoiceSettings.tts_provider: str="zonos"`. Inyección prompt: `kateto/voices/prompt_blocks.py` `{provider: block_fn}`; `_messages_for` anexa `get_agent_prompt_block()` si tts_provider=="boson" y depts∩{"fun"}.
- **F12 Visual overlay:** `VisualOverlayPlugin` escucha text_chunk (subtítulos), voice_status, PCM → envelope RMS → visema on/off. Reusar `system/http_server.py` (FastAPI+uvicorn): WS `/ws/overlay` + StaticFiles. Frontend `visual_overlay/web/` (index.html+canvas, fondo transparente, sprites top.png+mouth.png, bobbing, subtítulos). Decisión: reimplementar-lite (no puente Veadotube).

### NUEVA — F11b Inter-voz "generar" (NO estaba en plan de prometheus, AGREGADA por el humano)
- Una voz debe poder enviar a otra voz un evento de "generar" (p.ej. Jane=fun → Doktor=management "generá X"), vía bus (target routing) y/o MCP entre voces.
- Definir evento `GenerateRequestData` (target_voice:str, prompt:str, source_voice:str, depth:int=0, dept:str|None=None) en core/event.py. O reusar trigger `generate` con target=<otra_voz>.
- Tool de voz `request_generation(target_voice, prompt)` que emite GenerateRequest con target seteado. Voz destino lo recibe en su queue y genera.
- Si las voces se exponen como servidores MCP entre sí (bus→MCP), el evento generate debe poder viajar por ese canal.
- Respetar dept (anti-spoofing de F10). Guardraíl: cap de depth (no cadena infinita).

## RIESGOS (de prometheus, tenelos en cuenta)
- R3 X11 vs Wayland: `echo $XDG_SESSION_TYPE`. mss cubre pantalla completa en ambos.
- R4 PulseAudio vs PipeWire (Arch default PipeWire): pw-record/pw-loopback sin dep. Marcar experimental.
- R5 importlib.reload no recarga sub-módulos: limpiar sys.modules del paquete hijo.
- R6 chromadb+torch+whisper+Zonos en misma máquina: medir footprint.
- R9 _compact_history_data trunca bytes >4KB pero despacha envelope original íntegro: VisionFrame llega completo.
- R10 dept en TUI/MCP: campo con default no rompe.

## ORDEN SUGERIDO
M1 (10 dept → 5 safe soul → 6 hot reload) → M2 (1 sched → 3 tool → 4 capa) → M3 (8,9) → M4 (7,2,11,12) + 11b inter-voz.

## ENTREGAR
- Commits por feature (uno o más). Mensajes tipo conventional (`feat(core): dept field en EventEnvelope`).
- Tests pytest-asyncio para cada feature (ver nombres en plan).
- No romper los 41 tests existentes (salvo los 7 de collection-error ya rotos por módulo kateto.qa externo).
- Reportá al final: qué features quedaron hechas, cuáles parciales, y blockers (p.ej. API key Boson, X11/Wayland del host).
