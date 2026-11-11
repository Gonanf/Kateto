# Known Issues Register (.pm/docs/known-issues.md)

Este registro documenta los problemas encontrados, analizados y resueltos durante el desarrollo de Hipotenusa y el modo judicial Bate Debate.

---

## 1. Problemas Recientes (Bate Debate Judicial)

### Issue #70: Visual Overlay Basic Restoration & TTS Interruption Resilience
- **Estado:** ✅ Resuelto (2026-08-31)
- **Severidad:** Alta
- **Componentes:** `hipotenusa/plugins/visual_overlay/web/index.html`, `hipotenusa/plugins/visual_overlay/web/courtroom.html`, `hipotenusa/plugins/audio_output/player.py`, `hipotenusa/plugins/audio_output/camb.py`
- **Problema 1 (Visual Overlay Básico Contaminado):** `index.html` había sido modificado con `<hipotenusa-subtitles>` adoptando la apariencia del courtroom en lugar del overlay transparente OBS original.
  - **Solución:** Se restauró `index.html` a su diseño original puro con Datastar, capas cinemáticas y subtítulo flotante `#caption`.
- **Problema 2 (Bloqueo del TTS tras Interrupción o Streaming):** En `player.py`, el flag `_interrupted` no se limpiaba al cerrar el stream, bloqueando todo audio posterior de la misma voz; en `camb.py`, `on_text_chunk` cancelaba incondicionalmente el stream anterior, rompiendo el streaming de frases sucesivas de una misma voz; en `courtroom.html`, la retirada de `<hipotenusa-subtitles>` eliminó la síntesis de voz en el navegador.
  - **Solución:** Limpieza estricta de `_interrupted` con ventana temporal en `player.py`, cancelación en `camb.py` solo ante interrupción real o cambio de voz, y síntesis directa Web Speech API en `courtroom.html` con detección de audio de backend.

### Issue #69: TTS Concurrency, PortAudio Crash, Long Delays & Missing SOUL.md
- **Estado:** ✅ Resuelto (2026-08-29)
- **Severidad:** Alta
- **Componentes:** `hipotenusa/plugins/audio_output/player.py`, `hipotenusa/plugins/audio_output/camb.py`, `hipotenusa/plugins/bate_debate/orchestrator.py`, `hipotenusa/cli/commands.py`
- **Problema 1 (SIGSEGV en Interrupción):** `on_interrupt` llamaba a `_close_stream()` en el hilo principal mientras `stream.write` se ejecutaba concurrentemente en un worker thread de AnyIO en la librería C de PortAudio, provocando puntero nulo / use-after-free (`SIGSEGV`).
  - **Solución:** `on_interrupt` solo activa la bandera cooperativa `self._interrupted = True`. El bucle de escritura de 20ms sale de forma limpia en el hilo principal antes de cerrar el stream con seguridad.
- **Problema 2 (Orador interrumpido seguía hablando):** `camb.py` no cancelaba la tarea anterior (`self._stream_task`) al recibir un nuevo `TextChunk` y reseteaba `_interrupted = False`, disparando peticiones concurrentes a la API de Camb.ai. En `player.py`, los paquetes de audio restantes en la cola se seguían reproduciendo.
  - **Solución:** `camb.py` cancela activamente cualquier tarea previa (`await self._cancel_stream()`) y purga su cola de mensajes en interrupción. `player.py` descarta de inmediato cualquier paquete residual del orador interrumpido (`_interrupted_voice`).
- **Problema 3 (Delays excesivos entre turnos):** La estimación de duración utilizaba 0.38s/palabra (muy lento frente a los 0.24s reales de TTS moderno a ~230 WPM) e ignoraba los 3 a 6 segundos consumidos por el LLM local durante el prefill y generación.
  - **Solución:** Ajuste a `words * 0.24` y cálculo diferencial mediante `_wait_for_turn(text, started_at=time.monotonic())`, deduciendo el tiempo de prefill transcurrido mientras el audio previo ya estaba sonando.
- **Problema 4 (SOUL.md no se cargaba):** El orquestador generaba prompts con `_PROFILES[voice_id].system_prompt`, omitiendo los archivos `SOUL.md` de usuario (`~/.config/hipotenusa/voices/{voice}/SOUL.md`).
  - **Solución:** Implementación de `_load_voice_soul(voice_id, config_dir)` con precedencia completa (`user config > defaults > factory`).

### Issue #68: Debate Hang, WebSocket Cleanup & Courtroom State
- **Estado:** ✅ Resuelto (2026-08-29)
- **Severidad:** Media
- **Componentes:** `hipotenusa/cli/commands.py`, `hipotenusa/plugins/visual_overlay/web/courtroom.html`, `hipotenusa/plugins/system/http_server.py`
- **Problema:** Respuestas sin `max_tokens` colgaban la inferencia; cierre con `^C` provocaba advertencias `Task was destroyed but it is pending!`; desconexión de WebSocket por inactividad durante pensamiento del LLM; pérdida de estado en la interfaz web al recargar.
- **Solución:** `max_tokens=256` configurable, cierre ordenado de tareas en el broadcaster, `ping_interval=15` en WebSockets, y almacenamiento / restauración automática de estado en el courtroom.

### Issue #67: Hardcoded HipotenusaTalker & Missing Real LLM Provider in Debate CLI
- **Estado:** ✅ Resuelto (2026-08-29)
- **Severidad:** Alta
- **Componentes:** `hipotenusa/cli/commands.py`, `hipotenusa/plugins/bate_debate/orchestrator.py`
- **Problema:** La CLI forzaba el modelo quemado `HipotenusaTalker` provocando 404 en servidores OpenAI locales, y no permitía pasar argumentos de delay o tema.
- **Solución:** Lectura dinámica del modelo configurado (`config.plugins.llm_endpoint.model`) y soporte CLI completo para `--model`, `--delay`, `--topic`.

---

## 2. Issues Históricos del Runtime Hipotenusa

| ID | Título | Severidad | Estado | Componente |
|---|---|---|---|---|
| 62 | Camb.ai TTS: repetición de frases por reenvío de buffer | Alta | ✅ Resuelto | `hipotenusa/plugins/audio_output/camb.py` |
| 63 | PortAudio ALSA: xrun assertion crash | Alta | ✅ Resuelto | `hipotenusa/plugins/audio_output/player.py` |
| 64 | Whisper: validación de transcripciones vacías | Media | ✅ Resuelto | `hipotenusa/plugins/audio_processor/whisper.py` |
| 65 | Subtítulos: desincronización con el flujo de audio TTS | Media | ✅ Resuelto | `hipotenusa/plugins/visual_overlay/` |
| 66 | WhisperProvider: omisión de settings de idioma | Baja | ✅ Resuelto | `hipotenusa/plugins/audio_processor/whisper.py` |
| 67 | Debate CLI: hardcode de modelo y falta de flags dinámicos | Alta | ✅ Resuelto | `hipotenusa/cli/commands.py` |
| 68 | Debate CLI: max_tokens infinito y bloqueo en WebSockets | Media | ✅ Resuelto | `hipotenusa/cli/commands.py` |
| 69 | Debate TTS: latencia de 15s y delay inflado | Alta | ✅ Resuelto | `hipotenusa/plugins/audio_output/` |
| 70 | Visual Overlay: restauración de index.html y resiliencia de interrupción | Alta | ✅ Resuelto | `hipotenusa/plugins/visual_overlay/`, `hipotenusa/plugins/audio_output/` |
| 71 | Bate Debate: refactorización a bus de eventos nativo y preservación de SOUL.md | Alta | ✅ Resuelto | `hipotenusa/plugins/bate_debate/orchestrator.py`, `hipotenusa/voices/base.py` |
| 72 | Configuración por carpeta de voz y registro dinámico de parámetros de plugins | Media | ✅ Resuelto | `hipotenusa/core/config.py`, `hipotenusa/plugins/audio_output/boson_tts_plugin.py` |
| 73 | Debate TTS: repetición de voz en navegador y TimeoutError en generate_turn | Alta | ✅ Resuelto | `hipotenusa/plugins/bate_debate/orchestrator.py`, `hipotenusa/plugins/visual_overlay/web/courtroom.html` |
| 74 | Bate debate: solapamiento prematuro de oradores y voces en tercera persona o eco textual | Alta | ✅ Resuelto | `hipotenusa/plugins/bate_debate/orchestrator.py` |
| 75 | Visual overlay: soporte para reproducción de audio TTS en navegador y layout multi-agente configurable | Media | ✅ Resuelto | `hipotenusa/plugins/visual_overlay/` |
| 76 | Visual overlay: filtrado estricto por ventana y posicionamiento programático para juegos (Chess/Versus/Sides) | Media | ✅ Resuelto | `hipotenusa/plugins/visual_overlay/` |
| 77 | OpenAI-compatible API Server: interfaz HTTP /v1/chat/completions sobre el bus de eventos de Hipotenusa | Media | ✅ Resuelto | `hipotenusa/plugins/system/openai_server.py` |
| 78 | Debate TTS double speech y corte instantáneo de audio en interrupciones con EdgeTTS | Alta | ✅ Resuelto | `hipotenusa/plugins/system/http_server.py`, `hipotenusa/plugins/audio_output/` |
| 79 | Barrera wait_idle en Plugin y sincronización determinista de turnos de voz TTS | Alta | ✅ Resuelto | `hipotenusa/core/plugin.py`, `hipotenusa/plugins/audio_output/` |
| 80 | Streaming PCM chunked en EdgeTTS e interrupción por cue implantado en objeciones | Media | ✅ Resuelto | `hipotenusa/plugins/audio_output/edgetts.py`, `hipotenusa/plugins/bate_debate/` |
| 81 | PortAudio ALSA assertion crash, stream persistence and debate turn pacing | Alta | ✅ Resuelto | `hipotenusa/plugins/audio_output/player.py`, `hipotenusa/plugins/audio_output/edgetts.py`, `hipotenusa/plugins/bate_debate/` |
| 82 | Interrupción de voz global mutando al siguiente orador y deadlock en feed de FFmpeg | Alta | ✅ Resuelto | `hipotenusa/plugins/audio_output/edgetts.py`, `hipotenusa/providers/edgetts.py`, `hipotenusa/plugins/bate_debate/` |
| 83 | Interrupción fantasma en http_server silenciando la objeción entrante | Crítica | ✅ Resuelto | `hipotenusa/plugins/system/http_server.py` |
| 84 | Stream de PortAudio inactivo tras stream.abort() silenciando todo audio posterior | Crítica | ✅ Resuelto | `hipotenusa/plugins/audio_output/player.py` |
| 85 | Fuga de bandera _playing en EdgeTTS causando congelamiento de 45s en wait_idle | Crítica | ✅ Resuelto | `hipotenusa/plugins/audio_output/edgetts.py`, `hipotenusa/plugins/bate_debate/` |
| 86 | ALSA mmap xrun en streams persistentes y demora artificial en cue de objeción | Crítica | ✅ Resuelto | `hipotenusa/plugins/audio_output/player.py`, `hipotenusa/plugins/bate_debate/` |


