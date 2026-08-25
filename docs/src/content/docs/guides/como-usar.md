---
title: Cómo usar Kateto
description: Guía práctica para instalar, configurar y correr Kateto — CLI completo, voces, skills y modo sin servidores.
---

# Cómo usar Kateto

## Requisitos

- **Python 3.12+** y [uv](https://docs.astral.sh/uv/) como gestor de proyecto.
- Para el runtime con audio real: servidores externos de inferencia (whisper.cpp, llama.cpp, TTS) o **binarios locales invocados por subprocess** (ver [Sin servidores](#modo-sin-servidores-localcommandprovider)). El modo `--fixture` no necesita red.

## Instalación

```bash
git clone <repo-de-kateto>
cd Kateto
uv sync
```

## Comandos del CLI

| Comando | Qué hace |
|---|---|
| `uv run kateto config check` | Valida el TOML y bootstrap de defaults |
| `uv run kateto setup` | **Wizard interactivo**: configura LLM, Whisper y TTS; escribe `config.toml` (deep-merge con defaults) y las secrets a `secrets/.env` |
| `uv run kateto doctor` | **Reporte de salud**: valida config, silero-vad/torch, API keys (enmascaradas), reachability de servers y modelos de Ollama (incluye probe de tool-calling) |
| `uv run kateto run` | Event runtime (sin TUI) — el camino real |
| `uv run kateto tui` | Text UI con event stream (deprecada; el reemplazo es el Dashboard) |
| `uv run kateto tui --fixture` | TUI con fixtures determinísticos |
| `uv run kateto smoke --fixture` | Smoke test acotado sin red |
| `uv run kateto install <source>` | Instala un pack de voces/skills (git URL o path local); `--force` para pisar; `--from-agency` convierte un repo agency-agents |
| `uv run kateto trace` | Traza el runtime (de la campaña ops-ux) |

### Setup

`kateto setup` es interactivo: pregunta LLM base URL + model, Whisper ASR URL, Zonos TTS URL y la Camb AI API key (opcional). Hace deep-merge con los defaults y escribe:

- `~/.config/kateto/config.toml` — config del usuario
- `~/.config/kateto/secrets/.env` — API keys (referenciadas como `env:KATETO_CAMB_API_KEY`)

### Doctor

`kateto doctor` devuelve checks con `[ok]`/`[FAIL]`:

- **config** — el TOML parsea y valida contra `KatetoConfig`
- **vad** — silero-vad + torch importables
- **keys.{plugin}** — api_key presente (enmascarada: `sk-ef2...6599`)
- **server.whisper / server.tts.zonos / server.tts.camb** — reachability por HTTP
- **ollama** — si el voice LLM apunta a `:11434`: modelos presentes/cargados y probe de tool-calling (si el modelo no emite `tool_calls`, las tools de voz no van a andar)

Salida típica:

```
[ok] config: config.toml validates
[ok] vad: silero-vad + torch available
[ok] keys.audio_output_camb: api_key present (KATE...EY)
[FAIL] server.whisper: unreachable — start it, then re-run `kateto doctor`
```

### Install (packs de voces/skills)

Un **pack** es un repo/directorio con:

```
voices/<id>/SOUL.md      # system prompt de la voz
skills/<name>/SKILL.md   # skill de la voz
```

```bash
# desde un git URL o un path local
uv run kateto install https://github.com/alguien/pack-de-voces
uv run kateto install /tmp/pack_local

# pisar lo existente
uv run kateto install /tmp/pack_local --force

# desde un repo agency-agents (divisiones engineering/, design/, etc.)
uv run kateto install https://github.com/alguien/agency-agents --from-agency
```

El conversor `--from-agency` mapea cada `*.md` con frontmatter YAML a `voices/<voice_id>/SOUL.md` (cuerpo = system prompt) + `skills/<voice_id>/SKILL.md`. Registro: `kateto/cli/registry.py` (`register_command`).

## Configuración

- Defaults en `config/defaults/config.toml` + `config/defaults/voices/{name}/workflows/`.
- Se copian con `_copy_missing_defaults()` al config dir del usuario (`~/.config/kateto/` o `$XDG_CONFIG_HOME/kateto`) **sin pisar archivos existentes**.
- Precedencia: config de usuario > `config/defaults/` > hardcode (factory.py).
- Todas las rutas de voces se resuelven con `config_dir / "voices" / voice_name`. Los defaults NO se usan en runtime — solo para el bootstrap inicial.

## Dónde viven las voces y cómo modificarlas

La config de usuario (NO tocar los defaults del repo) es la fuente de verdad para voces:

```
~/.config/kateto/
├── config.toml                  # enable/disable voces, providers, settings
├── secrets/.env                 # API keys
└── voices/
    ├── jane/
    │   ├── SOUL.md              # system prompt / personalidad de Jane
    │   ├── top.png / mouth.png  # sprites del overlay (si los tiene)
    │   └── workflows/<name>/workflow.py   # workflows declarativos
    ├── doktor/
    └── conquest/
```

### Habilitar/deshabilitar una voz

En `config.toml`:

```toml
[voice.jane]
enabled = true

[voice.doktor]
enabled = false
```

### Modificar la personalidad de una voz

Editá `~/.config/kateto/voices/{nombre}/SOUL.md`. Kateto lo lee como `system_prompt` al crear la voz (`create_voice()` en `kateto/voices/factory.py`). La voz NO es un archivo de código: es un prompt. Cambiar el SOUL cambia el comportamiento sin tocar Python.

### Workflows

En `{voice_dir}/workflows/{name}/workflow.py`: campos `name`, `description`, `voice`, `phases` (array con id/instructions/deliverables/checkpoints). Se cargan con `WorkflowCatalog` (discovery case-insensitive) y los ejecuta `WorkflowEngine`.

### Instalar skills de una voz

```bash
uv run kateto install <pack-con-skills> --force
```

Copia `skills/<name>/SKILL.md` a `~/.config/kateto/skills/` y lo consume `_ensure_voice_skills()` en `kateto/voices/factory.py`. Copy-missing salvo `--force`.

## Modo sin servidores (LocalCommandProvider)

Kateto puede correr **sin levantar ningún server HTTP de inferencia**: los providers locales invocan un binario por subprocess en cada llamada. Se activan seteando `command` en el section del plugin; si NO hay `command`, se usa el provider HTTP.

```toml
[plugin.audio_processor_whisper]
command = "whisper-cli"
model = "/home/user/models/ggml-large-v3-turbo-q5_0.bin"   # model = PATH en modo local
args = ["-l", "es"]

[plugin.audio_processor_classifier]
command = "llama-cli"
model = "/home/user/models/clasificador.gguf"
```

- **Whisper local**: `whisper-cli -f <wav> -oj` → lee el JSON de transcripción.
- **Classifier local**: llama-cli/ONNX con salida JSON estructurada (`ClassificationPayload`).
- El LLM de voces sigue siendo HTTP-only hoy (`OpenAIAgentProvider`): para el voice_llm local hay que apuntar a un server OpenAI-compatible (ej. llama.cpp `llama-server`) o esperar el provider local de LLM.

### Compilar los binarios para Vulkan

Los binarios de whisper.cpp y llama.cpp **compilados con backend Vulkan** corren en la GPU (AMD/Intel/NVIDIA con drivers Vulkan) sin CUDA. Compilalos con OpenCode/agy (el coding lo hacen los agentes, no Kateto):

```bash
# whisper.cpp con Vulkan
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build -j --config Release
# → build/bin/whisper-cli

# llama.cpp con Vulkan
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build -j --config Release
# → build/bin/llama-cli (y llama-server para el voice_llm)
```

> En multi-GPU con Vulkan: `--tensor-split 0.5,0.5` reparte el modelo entre dos GPUs (ej. RX 6500 XT + Intel DG1). Ver `references/local-agentic-models.md` para el mapeo de modelos a voces/clasificador.

> Con Docker y autoinstalación: el repo trae `docker/` y `Dockerfile` — mirá esas rutas antes de compilar a mano.

## Probar el runtime en vivo

1. `uv run kateto run` — levanta el server HTTP en `:8080`.
2. Abrir el Dashboard (proyecto separado) o el overlay (`http://127.0.0.1:8080/overlay`).
3. Disparar eventos por el bus real:

```bash
curl -X POST http://127.0.0.1:8080/events/send \
  -H "Content-Type: application/json" \
  -d '{"event_name": "generate", "data": {"prompt": "Resumí el estado del proyecto"}}'
```

> Ojo: el contrato `GenerateData` rechaza `dept` por `extra_forbidden` — omitilo (el default es `fun`).

4. Escuchar el stream por `WS /events/stream`.

## Modo headless (discusión multi-voz)

Para usar Kateto como harness de discusión sin TTS: ver [Runtime headless](/runtime/headless/). La receta completa cubre config, `POST /events/send`, orquestación con Jane como jueza, y sincronización por inactividad.

## Comandos útiles para debugging

```bash
uv run kateto config check   # validar config
uv run kateto doctor         # salud del sistema (config, servers, keys, modelos)
uv run kateto smoke --fixture  # test acotado sin red
uv run pytest kateto/tests/test_event_bus.py -v  # tests específicos
```
