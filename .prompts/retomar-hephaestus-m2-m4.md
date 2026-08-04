# PROMPT HEPHAESTUS — RETOMAR implementación Kateto (M2→M4)

Sos Hephaestus (agente de implementación de OMO). Estás RETOMANDO un trabajo que se cortó a mitad de M2. NO vuelvas a hacer M1 (ya está commiteado y los tests core pasan).

## Repositorio
`/home/chaos/proyectos/OpenaiBuildWeek/Kateto/` — Python `kateto`, Python 3.12+, uv, Pydantic, Textual 8, MCP 1.28.

## ESTADO ACTUAL (verificado)
- **M1 COMPLETO y commiteado**: F10 (dept en EventEnvelope + filtro + anti-spoofing), F5 (SoulSnapshotStore ZODB + rollback en VoiceMemory), F6 (HotReloadController watchfiles), F11b (inter-voz generate evento + tool). Tests core: 29 passed.
- **M2 A MEDIAS (SIN COMMIT)**: `kateto/plugins/executor/scheduler.py` ya escrito (244 líneas) + contratos `ScheduleRequestData`/`ScheduleResultData`/`ScheduleCancelData` en `kateto/core/event.py` (modificado, sin commit). `pyproject.toml`/`uv.lock` modificados (watchfiles ya agregado en M1, pero F1 puede haber tocado deps). **PRIMERO**: commiteá los cambios sin commitear de F1 con mensaje `feat(scheduler): SchedulerPlugin + contratos (F1)`. Verificá que el scheduler se registre y los tests pasen.

## DECISIONES DEL HUMANO (vigentes)
- **R2:** ZODB para undo + logs de eventos en DB para debug. JSONL fallback. Event sourcing puro descartado.
- **R1:** croniter + engine asyncio propio (YA aplicado en F1 scheduler).
- **R7 (Boson.ai):** `POST https://api.boson.ai/v1/audio/speech`, `Authorization: Bearer <BOSON_API_KEY>`, body `{model:"higgs-tts-3"|"higgs-audio-v3-tts", input, voice?, ref_audio?, ref_text?, stream?:bool, response_format?:"mp3"}`. Devuelve mp3.

## QUÉ FALTA (continuá desde acá)
### M2 (terminar)
- **F3 Tool agenda:** tool builtin `schedule_event` en `kateto/voices/tools.py` → emite schedule_request → devuelve job_id. Guardraíles por voz. Gate Hermes: `disable_scheduling_tools: bool` en executor; factory ruta `conversation_id` (HermesProvider) lo setea + no inyecta cronjob-MCP.
- **F4 Capability:** un plugin emite su `schedule_request` en `enable()` (emit-in-enable). Documentar patrón.

### M3 (depende M1+M2)
- **F8 Static Vision:** `VisionFrameData` (frame:bytes, source_pid:int|None, ts, dept="fun"). `StaticVisionPlugin` en `kateto/plugins/static_vision/` auto-jitter vía scheduler; captura mss (pantalla completa), X11 python-xlib por PID, Wayland grim/slurp. Sin VLM en v1. Deps: mss, Pillow, python-xlib (opcional).
- **F9 Process Audio Whisper:** `ProcessTranscriptionData` (text, source_pid, ts, dept="fun", language?). `ProcessAudioWhisperPlugin` auto-jitter; captura audio de app (PulseAudio pulsectl null sink+loopback, o PipeWire pw-record/pw-loopback) → transcribe reusando whisper → emite. Dep: pulsectl (opcional).

### M4 (paralelo tras M2)
- **F7 Memoria vectorial:** `MemorySinkPlugin` suscrito a transcription/text_chunk/generate/voice_idle/tool_result → ChromaDB (PersistentClient, config dir). Metadata voice/type/ts/trace_id/dept. `VoiceAgent._messages_for` inyecta top-k semánticos (timeout corto, fail→skip). Embeddings: reusar endpoint OpenAI-compatible del LLM si expone /embeddings, fallback sentence-transformers. Dep: chromadb.
- **F2 Hermes:** `HermesProvider.manage_tools: bool=False` → no inyecta tools. Bridge v1 unidireccional. Bidireccional fuera de alcance.
- **F11 Boson TTS:** `BosonTTSProvider` HTTP (misma forma que zonos.py) + registro en `kateto/providers/` y `kateto/plugins/audio_output/`. `VoiceSettings.tts_provider: str="zonos"`. Inyección prompt: `kateto/voices/prompt_blocks.py` `{provider: block_fn}`; `_messages_for` anexa `get_agent_prompt_block()` si tts_provider=="boson" y depts∩{"fun"}.
- **F12 Visual overlay:** `VisualOverlayPlugin` escucha text_chunk (subtítulos), voice_status, PCM → envelope RMS → visema. Reusar `kateto/plugins/system/http_server.py` (FastAPI+uvicorn): WS `/ws/overlay` + StaticFiles. Frontend `kateto/plugins/visual_overlay/web/` (index.html+canvas, fondo transparente, sprites top.png+mouth.png, bobbing, subtítulos). reimplementar-lite.

## RIESGOS
- R3 X11 vs Wayland: `echo $XDG_SESSION_TYPE`. mss cubre pantalla completa en ambos. Marcar captura por PID como experimental en Wayland.
- R4 PulseAudio vs PipeWire (Arch default PipeWire): pw-record/pw-loopback sin dep. Experimental.
- R5 importlib.reload no recarga sub-módulos: limpiar sys.modules del paquete hijo (ya en F6).
- R6 chromadb+torch+whisper+Zonos en misma máquina: medir footprint, no bloqueante para implementar.
- R9 VisionFrame llega íntegro (envelope original no se compacta).

## ENTREGAR
- Commiteá por feature (conventional commits). Primero F1 (lo sin commitear), luego F3, F4, F8, F9, F7, F2, F11, F12.
- Tests pytest-asyncio para cada feature nueva.
- Corré `uv run pytest kateto/tests/test_event_bus.py kateto/tests/test_plugin_manager.py kateto/tests/test_config.py` al menos, y los tests de lo que toques. No romper los 29 que ya pasan.
- Reportá al final: features hechas / parciales / blockers (API key Boson, X11/Wayland del host, PipeWire vs PulseAudio).
