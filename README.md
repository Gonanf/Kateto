# Kateto

> Proyecto de Gonanf — colección personal.
> **Lenguaje principal (GitHub):** Python · **URL:** https://github.com/Gonanf/Kateto

## Qué es

Este repositorio forma parte de la colección de **Gonanf / Gabriel Solotorevsky** clonada en `/run/media/chaos/terciario/proyectos/Kateto`.

> **Nota:** README original preservado abajo en la sección "README original".

- **Path absoluto:** `/run/media/chaos/terciario/proyectos/Kateto`
- **Estado git:** último commit `2026-09-01 feat(debate): courtroom debate orchestrator, visual overlay, tts streaming, and audio pipeline stabilization`
- **Archivos (aprox):** 532
- **Stack detectado:** Python (pyproject.toml), Docker

## Stack

- Python (pyproject.toml)
- Docker

## Estructura

```
Kateto/
.codex
.dockerignore
.omo/
  .omo/boulder.json
  .omo/drafts
  .omo/plans
  .omo/start-work
  .omo/ulw-loop
.pm/
  .pm/docs
  .pm/items
  .pm/project.toml
.prompts/
  .prompts/f3-solo.md
  .prompts/implement-hephaestus.md
  .prompts/opencode-converter.txt
  .prompts/plan-features-prometheus.md
  .prompts/retomar-hephaestus-m2-m4.md
  .prompts/specs
.python-version
```

## Cómo correr

> Instrucciones genéricas según el stack detectado. Ajustar según el repo.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # o pip install -e .
python main.py  # ver entrypoints en repo
```

## Estado

- **Último commit:** `2026-09-01 feat(debate): courtroom debate orchestrator, visual overlay, tts streaming, and audio pipeline stabilization`
- **Clonado en:** `/run/media/chaos/terciario/proyectos/Kateto`
- **Exclusiones del lote:** Forks, Workmatch, el-hornero-digital, mali/meli, Sherut (no tocados por consigna)

## Docs

- `docs/overview.md` — descripción extendida y guía rápida (generado en este lote)

## README original (preservado)

> Contenido previo de README.md recortado a 2000 chars para referencia:

```markdown
# Kateto — Event-Driven Voice Team for Project Work

![Jane](public/jane1.svg) ![Doktor](public/doktor1.svg) ![Conquest](public/conquest1.svg)

Kateto is an autonomous, event-driven voice team designed for real-time project management and technical collaboration. Instead of forcing conversations through a brittle, linear request-response chain, Kateto runs an event-driven architecture where specialized voice agents, audio hardware, intent classifiers, and autonomous workflows interact concurrently through a centralized `PluginManager` event bus.

---

## 1. Architectural Overview

```
                        +----------------------------------------+
                        |        PluginManager (Event Bus)       |
                        +---+--------+--------+--------+-----+---+
                            |        |        |        |     |
      +---------------------+        |        |        |     +---------------------+
      |                              |        |        |                           |
+-----v-------+               +------v---+  +-v------+ v-------------+     +-------v--------+
| Audio Input |               | Whisper  |  | Intent | | Voice Agent |     | Audio Output   |
| (Mic + VAD) |               | Processor|  | Router | | (LLM + MCP) |     | (TTS + Player) |
+-------------+               +----------+  +--------+ +-------------+     +----------------+
  sounddevice                 whisper.cpp     mmBERT    Jane, Doktor,        Camb AI / Zonos
  Silero VAD                  Vulkan / CUDA  llama.cpp  Conquest             ALSA PCM Mixer
       |                           |             |            |                     |
       v                           v             v            v                     v
 [audio_chunk]             [transcription
```

---
*README generado/mejorado automáticamente el 2026-09-04 con inspección de repo (opencode/agy pattern: lectura de estructura, lenguaje y entrypoints). No se modificó código, solo documentación.*
*Autor original: Gonanf — https://github.com/Gonanf/Kateto*
