---
title: "Interrupción purga pipelines de otros departamentos (mic Fun corta voz Management)"
description: "Síntoma"
---


## Síntoma
El usuario habla un enunciado largo; el VAD Silero del mic de audio input mal-detecta
un fin de speech y dispara el pipeline de transcripción prematuramente. Se apilan varios
segmentos: cada uno recorre `transcription` -> `classification`(EXECUTE) -> `generate`
-> `speak` -> `_generation_task` de una voz -> TTS -> PCM en `AudioPipeline.pcm_queue`.
Cuando el usuario interrumpe (nuevo speech) o termina, todas las generaciones encoladas se
vierten al audio output una tras otra ("4 respuestas de una").

Requisito de producto: la purga disparada por un `interrupt` debe limitarse al/los
**departamento(s)** del mic de audio input que lo originó. Un mic con dept `fun` NO debe
cancelar ni purgar el agente/output del dept `management` (lo maneja otro agente).

## Causa raíz
1. `core/manager.py:146-158` `PluginManager.interrupt()` no tiene parámetro `dept` y no
   setea `envelope.dept`. Todo interrupt es global hoy.
2. `plugins/audio_input/listener.py:179-186` `_interrupt_playback()` llama
   `manager.interrupt(reason="voice_activity", source=...)` sin dept. `AudioInputPlugin`
   (`listener.py:34-41`) se construye sin `depts`, así que el mic no tiene identidad de
   departamento.
3. `plugins/executor/interrupt.py:18-35` `InterruptExecutor.on_interrupt()` itera **todos**
   los plugins y llama cada `on_interrupt` directamente, saltándose el filtro de departamento
   de suscriptores del bus (`core/manager.py:341`). Esto anula cualquier scope por dept: hoy
   un interrupt siempre llega a todos.
4. La purga es global en cada consumidor:
   - `voices/base.py:425-434` `VoiceAgent.on_interrupt` cancela el `_generation_task` actual
     pero NO purga `AudioPipeline.token_queue` / `pcm_queue` (`base.py:68,74-75`); los tokens
     ya encolados siguen drenando al TTS.
   - `plugins/audio_output/zonos.py:103-110` `on_interrupt` cancela `_pipeline_tasks` pero deja
     `pipeline.pcm_queue` poblada.
   - `plugins/audio_output/player.py:174-182` `on_interrupt` limpia `_active_pipelines` /
     `_pipeline_queues` de **todas** las voces, ignorando el dept.
   Ninguno es dept-aware.

## Pasos para reproducir
1. Configurar un mic de audio input con dept `fun` y una voz del dept `management` activa y
   generando (p.ej. tarea larga en curso).
2. Hablar un enunciado largo con una pausa > `silence_timeout` (default 1.5s) para que el VAD
   segmente y dispare transcripción -> classification EXECUTE -> speak -> generación Fun.
3. Volver a hablar (nuevo speech) -> el mic emite `interrupt` (reason="voice_activity").
4. Observar: la generación/pipeline de la voz `management` también se cancela/purga, cuando
   solo debería afectar a las voces Fun.

## Impacto
- Interrupciones cruzadas entre departamentos: un usuario en `fun` silencia al agente
  `management` (u otro dept) que está operando en paralelo.
- Apilamiento de respuestas: múltiples generaciones encoladas se reproducen en secuencia al
  terminar de hablar, porque el interrupt no vacía las colas data-plane ya pobladas.

## Fix sugerido (NO aplicado — scope: solo el dept del mic origen)
El interrupt pasa a ser dept-scoped de punta a punta; el filtro de departamento del bus
(`core/manager.py:341`) es la única fuente de verdad. Cuando un mic dispara un interrupt,
solo los plugins cuyo `depts` incluye ese departamento reaccionan; la voz/agente/output del
dept `management` queda intacto.

### Lista de cambios
1. **El mic input gana un departamento.** Agregar el/los dept configurado(s) del mic a
   `AudioInputConfig` / `AudioInputIdentity` (`plugins/audio_input/base.py:54-117`) y
   forwardearlos a `AudioInputPlugin.__init__(depts=...)` (`listener.py:34-41`). Fuente: su
   `PluginSettings` (o un nuevo campo `dept` en `AudioInputConfig`).
2. **El interrupt lleva el departamento.** `PluginManager.interrupt()` (`core/manager.py:146-158`)
   gana `dept: str | None = None` y lo forwardea a `emit(..., dept=dept)` (emit ya soporta
   `dept`). `listener._interrupt_playback()` (`listener.py:179-186`) pasa `dept=<dept del mic>`.
   Agregar `dept: str | None = None` a `InterruptData` (`core/event.py:117-118`) para que los
   consumidores que solo ven el payload (no el envelope) sepan el scope; setearlo en
   `manager.interrupt`.
3. **Cortar el re-broadcast ciego.** `InterruptExecutor.on_interrupt()` (`interrupt.py:18-35`) NO
   debe iterar todos los plugins. Delegar en el filtro de suscriptores del bus para entregar
   `on_interrupt` solo a plugins que matchean dept. Mantener el dedupe `_interrupted` y las
   notificaciones `conversation_interrupted` / `conversation_resumed`, pero NO forwardear el
   interrupt a plugins fuera del dept. (Opción simple: borrar el loop y dejar que el bus haga su
   trabajo.)
4. **Purga dept-scoped en cada consumidor.**
   - `VoiceAgent.on_interrupt` (`voices/base.py:425-434`): tras cancelar `_generation_task`,
     reemplazar `AudioPipeline.token_queue` y `pcm_queue` (`base.py:519-524`, `_PIPELINES`) por
     colas vacías frescas, para que no drene ningún token viejo. Como el bus solo entrega el
     interrupt a voces del dept matcheante, esto queda automáticamente scoped (sin check extra
     tras el paso 3).
   - `ZonosAudioOutput.on_interrupt` (`zonos.py:103-110`) y `AudioOutputPlayer.on_interrupt`
     (`player.py:174-182`): son shared (sin dept) y por eso reciben interrupts de todos los dept.
     Deben purgar SOLO los pipelines que pertenecen a voces del departamento del interrupt. En el
     handler, leer `data.dept`, buscar en `manager.get_plugins()` las voces (`"voice" in
     capabilities`) cuyo `depts` contiene ese dept, recolectar sus `voice_id`, y cancelar/limpiar
     solo esos `AudioPipeline` (cancelar tareas de generación/consumo + reemplazar las dos colas).
     NO tocar los pipelines de otros dept.
5. **Mitigación de false-trigger del VAD (adyacente, no el fix):** ajustar `silence_timeout` /
   `vad_threshold` (`plugins/audio_input/base.py:18-24`, default 1.5s) para que enunciados largos
   con pausas naturales no se segmenten prematuramente. Reduce la frecuencia; la purga dept-scoped
   es la garantía real.

## Auditoría de hardcodeo (resumen para el implementador)
El sistema NO tiene pipelines ni plugins hardcodeados. Es 100% event-bus + discovery por
convención (`core/discovery.py` itera `kateto/plugins/*/__init__.py` -> `create_plugins(ctx)`;
`core/plugin.py` descubre handlers por `on_<evento>`; `manager.py` resuelve suscriptores por
filtros dept/capability/target). Los únicos "nombres fijos" son contratos de evento legítimos:
- `plugins/executor/classifier.py:77` -> `emit("generate", target="voice_manager")` (target
  hardcodeado a un plugin específico; el único en el flujo de vivo).
- `run_mode.py:111` -> `plugin.name == "workflow_engine"` (wiring de arranque, no runtime).
- `plugins/system/voice_manager.py:23` -> `_DEFAULT_PROBABILITIES` (default de config,
  overridable).
- `plugins/audio_input/base.py:18-24` -> `DEFAULT_SILENCE_TIMEOUT`, `DEFAULT_VAD_THRESHOLD`
  (constantes de tuning, overridables).
- `voices/base.py:208` / `core/plugin.py:21` -> `immediate_events` frozensets (convención de
  clase).
- DEAD CODE: `plugins/audio_processor/process_audio_whisper_plugin.py` (usa
  `ProcessTranscriptionData`) NO está en `audio_processor/__init__.py` `create_plugins`, por lo
  que ni se carga. El flujo real usa `whisper.py` + evento `audio_chunk`/`transcription`.

## Archivos afectados
- `core/manager.py` (`interrupt`)
- `core/event.py` (`InterruptData`)
- `plugins/audio_input/base.py` (`AudioInputConfig` / `Identity`, agregar dept)
- `plugins/audio_input/listener.py` (`AudioInputPlugin.__init__`, `_interrupt_playback`)
- `plugins/executor/interrupt.py` (`on_interrupt` remover broadcast)
- `voices/base.py` (`on_interrupt` purge, `_PIPELINES` / colas de pipeline)
- `plugins/audio_output/zonos.py` (`on_interrupt` purge dept-scoped)
- `plugins/audio_output/player.py` (`on_interrupt` purge dept-scoped)

## Acceptance criteria
- Mic configurado con dept `fun` dispara interrupt -> solo se purgan los pipelines /
  generaciones de voces Fun; el `_generation_task` y `pcm_queue` de una voz `management` quedan
  intactos y siguen sonando.
- Un interrupt de mic `management` NO purga pipelines Fun.
- Ningún plugin recibe `on_interrupt` para un dept que no le corresponde (entrega única, sin
  doble manejo desde `executor_interrupt`).
- Tests existentes de VAD pasan: `tests/test_audio_input.py::test_vad_interrupts_active_playback_once_per_playback_window`,
  `::test_vad_interrupts_llm_even_when_output_status_is_idle`.
- Nuevo test: un interrupt scoped a dept `fun` deja el `_generation_task` de una voz
  `management` corriendo (no cancelado).

## Fuera de scope
- `process_audio_whisper_plugin.py` (`ProcessTranscriptionData`) es dead code (no está en
  `audio_processor/__init__.py create_plugins`); no es parte de este fix.
- Cambiar el modelo VAD o la lógica de re-segmentación más allá del tuning de umbrales.
