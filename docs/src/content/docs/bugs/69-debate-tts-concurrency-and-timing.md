---
id: 69
title: "Debate TTS: SIGSEGV en interrupciones PortAudio, concurrencia en Camb.ai, delays inflados y omisión de SOUL.md"
severity: Alta
status: resolved
component: kateto/plugins/audio_output/, kateto/plugins/bate_debate/
resolved: 2026-08-29
---

## 69. Debate TTS: SIGSEGV en interrupciones PortAudio, concurrencia en Camb.ai, delays inflados y omisión de SOUL.md

**Severidad:** Alta
**Componente:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/camb.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/cli/commands.py`

### Descripción

Durante el desarrollo y pruebas en vivo del debate judicial (`kateto debate --overlay`):
1. **Fallo de segmentación (SIGSEGV):** Al ocurrir una objeción, el evento `interrupt` cerraba el stream de audio (`_close_stream()`) desde el hilo principal mientras un worker thread de AnyIO escribía chunks de audio mediante `to_thread.run_sync(stream.write, chunk)` en la librería C de PortAudio, provocando un puntero nulo / Use-After-Free y la caída inmediata de `kateto run`.
2. **El orador interrumpido continuaba hablando:**
   - En `camb.py`, la recepción de un nuevo `TextChunk` o la llamada a `on_interrupt` no cancelaba la tarea en curso `self._stream_task` y reseteaba `self._interrupted = False`. Ambas tareas (la del orador original y la del objetor) continuaban disparando peticiones concurrentes a la API de Camb.ai.
   - En `player.py`, los paquetes de audio restantes en la cola para el agente interrumpido se seguían reproduciendo porque `self._interrupted` se restablecía a `False` con cada nuevo `audio_output`.
3. **Delays excesivos entre agentes:**
   - El cálculo de espera estimaba la locución a 0.38s/palabra (muy por debajo de los ~220 WPM / 0.24s reales de los motores TTS modernos), dejando varios segundos de silencio tras terminar el audio.
   - Las llamadas secuenciales al LLM local (ej. evaluar una objeción) tomaban de 3 a 6 segundos, y luego el orquestador volvía a dormir el tiempo completo del turno o de la introducción sin descontar el tiempo ya transcurrido mientras el audio sonaba de fondo.
4. **Omisión de SOUL.md:**
   - El orquestador de debate generaba los system prompts de cada voz usando únicamente las cadenas predeterminadas de `_PROFILES[voice_id].system_prompt`, ignorando por completo los archivos `SOUL.md` personalizados en `~/.config/kateto/voices/{voice_id}/SOUL.md` y `config/defaults/voices/{voice_id}/SOUL.md`.

### Impacto

- Caída del runtime completo por `SIGSEGV` ante objeciones.
- Voces superpuestas hablando al mismo tiempo tras una objeción.
- Silencios incómodos de 15 a 25 segundos entre turnos de debate.
- Pérdida de la personalidad y directivas configuradas en el `SOUL.md` de cada agente.

### Causa

- Concurrencia insegura entre PortAudio C y callbacks de eventos asyncio.
- Falta de cancelación de tareas y purga de cola en `camb.py` y `player.py`.
- Estimación estática de tiempo sin considerar la velocidad real del TTS ni la latencia del prefill de LLMs locales.
- Falta de resolución de la ruta `SOUL.md` en el módulo de debate.

### Solución aplicada

1. **Prevención de SIGSEGV en PortAudio ([`player.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/audio_output/player.py)):**
   - Se removió `self._close_stream()` concurrente de `on_interrupt`.
   - `on_interrupt` solo activa la bandera cooperativa `self._interrupted = True`. El bucle de escritura (ventanas de 20 ms) sale limpiamente en el hilo principal y cierra el stream de forma segura.
   - Se descartaron paquetes residuales del orador interrumpido mediante rastreo de `_interrupted_voice`.
2. **Cancelación estricta en [`camb.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/audio_output/camb.py):**
   - `on_text_chunk` cancela cualquier stream anterior con `await self._cancel_stream()` antes de iniciar una nueva tarea.
   - `on_interrupt` cancela el stream y vacía la cola pendiente de chunks.
3. **Calibración de tiempo y compensación de latencia LLM ([`orchestrator.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/bate_debate/orchestrator.py)):**
   - Se ajustó la estimación de locución a `words * 0.24` (220-240 WPM).
   - Se implementó `_wait_for_turn(text, started_at)` midiendo `time.monotonic()`, deduciendo automáticamente el tiempo transcurrido durante la generación y prefill de LLMs locales.
4. **Carga jerárquica de SOUL.md ([`orchestrator.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/plugins/bate_debate/orchestrator.py), [`commands.py`](file:///home/chaos/proyectos/OpenaiBuildWeek/Kateto/kateto/cli/commands.py)):**
   - Se creó `_load_voice_soul(voice_id, config_dir)` respetando la precedencia de Kateto (`user config > defaults > factory`).
   - Se pasó `config_dir` desde `cmd_debate` en la CLI hacia el orquestador.

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/plugins/audio_output/camb.py`, `kateto/plugins/bate_debate/orchestrator.py`, `kateto/cli/commands.py`
