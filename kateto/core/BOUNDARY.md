# Frontera Arquitectónica del Core de Kateto (BOUNDARY)

> **La regla en una frase:**
> *El Core no importa `kateto.voices` ni `kateto.mask`; si necesita algo de ahí, recibe un contrato/protocolo en vez de importarlo.*

---

## 1. La regla fundamental

El subsistema `kateto/core/` representa la infraestructura base y agnóstica de Kateto (bus de eventos, ciclo de vida de plugins, configuración base, almacenamiento atómico y motor de workflows). Su diseño exige aislamiento unidireccional estricto: los módulos de capas superiores (`kateto.voices`, `kateto.mask`, `kateto.plugins`) pueden depender e importar el Core, pero **el Core nunca debe importar hacia arriba**. Si un componente del Core necesita invocar comportamiento de agentes, voces o hardware, debe interactuar mediante abstracciones, eventos o contratos/protocolos inyectados desde el ensamblado exterior.

---

## 2. Inventario de los 19 sistemas y reglas derivadas

> **Nota sobre veredictos:** En la auditoría base (§1 de `ARQUITECTURA-CORE.md`), todos los sistemas fueron catalogados únicamente como `CORE` o `HIPOTENUSA`, ya que Thales no cuenta hoy con presencia activa en el repositorio (0 apariciones). Las capacidades orientadas a productividad y tareas autónomas (`tools de trabajo` y `servidor MCP`), identificadas en §4 de dicha auditoría como la base de un runtime de trabajo sin voz, se catalogan en esta tabla como `THALES (futuro)` para delimitar la frontera respecto a la infraestructura nuclear.

| sistema | archivos:línea | veredicto | regla que se deriva |
| :--- | :--- | :--- | :--- |
| bus de eventos + ciclo de vida de plugins | `kateto/core/manager.py:38`<br>`kateto/core/event.py:37`<br>`kateto/core/plugin.py:23` | `CORE` | El bus y el gestor de ciclo de vida son infraestructura agnóstica; no deben contener nombres ni reglas de ruteo específicas de agentes de entretenimiento. |
| config | `kateto/core/config.py:115` | `CORE` | La configuración central solo debe validar opciones de infraestructura; esquemas específicos de audio/voz deben cargarse mediante extensiones de plugins. |
| storage | `kateto/core/storage.py:77`<br>`kateto/core/storage.py:18` | `CORE` | La persistencia y el sandboxing de paths pertenecen al Core, pero deben operar sobre espacios de nombres genéricos (`NamespaceFileStore`) sin acoplarse al concepto de voz. |
| descubrimiento de plugins | `kateto/core/discovery.py:56` | `CORE` | El Core descubre plugins genéricos por introspección; el registro e instanciación de personalidades de voz debe inyectarse desde el runtime exterior (`live.py`), nunca desde el Core. |
| workflow engine | `kateto/core/workflow_engine.py:46`<br>`kateto/core/workflow.py:92` | `CORE` | La máquina de estados de workflows orquesta fases abstractas; la resolución de destinatarios debe interactuar con protocolos tipados (`ActorProfile`) en lugar de clases concretas de voz. |
| memoria por voz | `kateto/voices/memory.py:27` | `HIPOTENUSA` | La gestión de personalidad y persistencia narrativa (`SOUL.md`, `MEMORIES.md`) es dominio exclusivo de Hipotenusa; ningún componente del Core debe importar `VoiceMemory`. |
| ledger de conversación | `kateto/voices/ledger.py:50` | `HIPOTENUSA` | El registro indexado de interacciones habladas en tiempo real pertenece a la capa conversacional; el Core desconoce la existencia del ledger. |
| tools de voz | `kateto/voices/tools.py:48` | `HIPOTENUSA` | Las herramientas especializadas de personajes y edición de soul residen fuera del Core; el Core solo provee el mecanismo para ejecutar tools arbitrarias. |
| audio input/VAD | `kateto/plugins/audio_input/silero.py:25`<br>`kateto/plugins/audio_input/mic.py:27`<br>`kateto/plugins/audio_input/capture.py:30` | `HIPOTENUSA` | La captura de hardware de micrófono y VAD son plugins periféricos de Hipotenusa; se comunican al Core exclusivamente vía eventos estándar (`EventEnvelope`). |
| audio output/TTS | `kateto/plugins/audio_output/player.py:32`<br>`kateto/plugins/audio_output/zonos.py:28`<br>`kateto/plugins/audio_output/camb.py:33`<br>`kateto/plugins/audio_output/edgetts.py:33` | `HIPOTENUSA` | Los motores de síntesis vocal y salida PCM son adaptadores externos; el Core desconoce los backends de audio específicos. |
| ASR / audio processor | `kateto/plugins/audio_processor/whisper.py:28`<br>`kateto/plugins/audio_processor/parakeet.py:31` | `HIPOTENUSA` | La transcripción de voz a texto opera como plugin periférico; emite eventos de texto sin que el Core dependa de Whisper o Parakeet. |
| gate de turno (EOT) / orquestación de turnos | `kateto/plugins/system/eot_gate.py:27`<br>`kateto/plugins/system/turn_gate.py:33` | `HIPOTENUSA` | La heurística de pausas de habla humana y arbitraje de interrupciones vocales es comportamiento de interacción de voz, no lógica de coordinación del Core. |
| checkpoints de estado (`mask/state_snapshots.py`, `mask/turn_durability.py`, `core/soul_store.py`, `voices/ledger.py`) | `kateto/mask/state_snapshots.py:22`<br>`kateto/mask/turn_durability.py:25`<br>`kateto/core/soul_store.py:21`<br>`kateto/voices/ledger.py:50` | `HIPOTENUSA` | Los snapshots de VRAM de modelos locales y durabilidad de frames son de Hipotenusa/máscara; el Core solo provee persistencia genérica transaccional desacoplada del parámetro `voice`. |
| tools de trabajo (`plugins/work/`, `plugins/executor/` backlog/todo) | `kateto/plugins/work/backlog.py:34`<br>`kateto/plugins/executor/todo_list.py:39`<br>`kateto/plugins/executor/todo_list.py:16` (uso en `:42`) | `THALES (futuro)` | Los ejecutores de productividad y tareas no deben acoplarse a identidades de voz (`_SHARED_VOICE`); deben operar como plugins agnósticos orientados al futuro runtime autónomo (Thales). |
| servidor MCP | `kateto/plugins/system/mcp_server.py:25`<br>`kateto/plugins/system/mcp_server.py:15` | `THALES (futuro)` | El servidor FastMCP debe exponer herramientas de sistema y trabajo sin importar directamente `kateto.voices.memory`; la inspección de memoria debe pasar por contratos o APIs desacopladas. |
| servidor HTTP/WS (`plugins/system/`) | `kateto/plugins/system/http_server.py:38` | `CORE` | La capa de transporte REST y WebSocket transporta eventos agnósticos; no debe condicionar payloads ni dependencias a dominios de voz o máscara. |
| providers | `kateto/providers/__init__.py:1`<br>`kateto/providers/agent.py:22`<br>`kateto/providers/llm.py:18` | `CORE` | Las interfaces de completado LLM y tool-calling son primitivas nucleares de IA reutilizables; los clientes de providers de voz (TTS/ASR) permanecen en Hipotenusa. |
| classifiers | `kateto/classifiers/mmbert/server.py:26`<br>`kateto/plugins/executor/classifier.py:25` | `CORE` | La clasificación semántica de intenciones hacia eventos es infraestructura del sistema; el Core despacha eventos resultantes sin conocer si provienen de audio o texto. |
| máscara (`mask/`) | `kateto/mask/audio_bridge.py:21` (import en `:10`)<br>`kateto/mask/state_snapshots.py:22`<br>`mask/hardware/cad/jaw_mount.scad:1` | `HIPOTENUSA` | El subsistema de máscara, servomotores físicos y frontend visual es 100% ajeno al Core; el Core nunca importa ni conoce la existencia de la máscara física ni del personaje Hannya. |

---

## 3. Deuda aceptada hoy — El Core actual NO es neutro: es "Hipotenusa sin la máscara" (violaciones explícitas)

El Core actual de Kateto **no es un núcleo neutro ni desacoplado**: es "Hipotenusa sin la máscara". Aunque no posee aristas hacia el subsistema de máscara física, se encuentra fuertemente acoplado en nombres, modelos de datos y flujos lógicos a la dimensión de voz y personalidades conversacionales. 

Esta es la lista cerrada de violaciones explícitas existentes hoy:

1. **Imports lazy hacia `kateto.voices` dentro de funciones del Core:**
   - `kateto/core/workflow_engine.py:290`: `from kateto.voices.base import VoiceProfile` (usado para resolver destinatarios de eventos comparando `VoiceProfile.display_name`).
   - `kateto/core/discovery.py:101`: `from kateto.voices.factory import create_voice as _factory` (invocado en `_scan_voices` para instanciar agentes de voz durante el escaneo).

2. **Conceptos de voz hardcodeados en el bus y gestor de eventos (`manager.py`):**
   - `kateto/core/manager.py:173`: razón default `"voice_activity"`.
   - `kateto/core/manager.py:384-389`: regla de seguridad y anti-spoofing que comprueba específicamente el departamento `"voice"` en plugins.

3. **Contaminación de voz y audio en la configuración central (`config.py`):**
   - `kateto/core/config.py:115`: atributo `default_voice_dept: str = "fun"`.
   - `kateto/core/config.py:128-132`: campos de audio `vad_model`, `vad_threshold`, `interrupt_on_vad`, `interrupt_tts`.
   - `kateto/core/config.py:163-190`: clase `VoiceSettings` con configuración de TTS (`tts_provider`, `camb_voice_id`, `edge_tts_voice`).
   - `kateto/core/config.py:282`: diccionario tipado `voice: dict[str, VoiceSettings]`.
   - `kateto/core/config.py:364`: función `_load_voice_folder_configs`.

4. **Acoplamiento léxico y semántico en almacenamiento (`storage.py`):**
   - `kateto/core/storage.py:77`: clase `VoiceFileStore`.
   - `kateto/core/storage.py:18`: excepción `PathIsolationError(voice)`.
   - `kateto/core/storage.py:87`: resolución fija a subdirectorio `config_dir / "voices" / voice`.

5. **Acoplamiento en el descubrimiento del Core (`discovery.py`):**
   - `kateto/core/discovery.py:100`: función `_scan_voices`.
   - `kateto/core/discovery.py:61-62`: assert de inicialización `"at least one P0 voice must be enabled"`.

6. **Acoplamiento en orquestación y modelos de workflow (`workflow_engine.py` y `workflow.py`):**
   - `kateto/core/workflow_engine.py:135`: handler `on_voice_idle`.
   - `kateto/core/workflow_engine.py:167`: handler `on_voice_enabled`.
   - `kateto/core/workflow.py:29-32`: excepción `WorkflowNotFoundError(workflow, voice)`.
   - `kateto/core/workflow.py:56,79`: atributo `calls_voices`.
   - `kateto/core/workflow.py:64,87`: campo `voice`.

---

## 4. Qué NO es Core ni Thales

- **La Máscara (`kateto/mask/`):** Representa el frontend visual y el hardware de servomotores físicos del personaje Hannya; existen exactamente **0 aristas de importación desde el Core** hacia `kateto.mask`.
- **Thales:** Es la hipótesis de un runtime headless autónomo para tareas de productividad; hoy tiene exactamente **0 apariciones en el repositorio** (cero código, cero documentación, cero issues).

---

## 5. Cómo se hace cumplir

La frontera arquitectónica se protege mediante un gate estático basado en AST que se ejecuta en CI y localmente como test de regresión:

- **Archivo del gate:** `kateto/tests/test_core_boundary.py`
- **Comando exacto para correrlo:**
  ```bash
  PYTHONPATH=. /home/chaos/proyectos/OpenaiBuildWeek/Kateto/.venv/bin/python -m pytest kateto/tests/test_core_boundary.py -q
  ```
  *(O usando uv: `uv run pytest kateto/tests/test_core_boundary.py -q`)*

### Política frente a nuevos imports
Si en el futuro se propusiera un nuevo import desde `kateto/core/` hacia `kateto.voices` o `kateto.mask`, este **será rechazado inmediatamente por el gate**. Si existe una razón justificada e intencional para agregarlo de forma transitoria como deuda técnica aceptada, el desarrollador debe:
1. Declararlo explícitamente en la lista `EXCEPCIONES` de `kateto/tests/test_core_boundary.py` indicando `(ruta_relativa, número_de_línea, módulo_importado)`.
2. Incluir en el mismo commit el comentario técnico que fundamente la excepción y el plan para su posterior desacoplamiento.
