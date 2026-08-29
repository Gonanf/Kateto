---
id: 62
title: "Camb AI TTS reproduce audio duplicado por re-emision de la respuesta final acumulada"
severity: Media
status: resolved
component: kateto/voices/base.py, kateto/plugins/audio_output/camb.py
resolved: 2026-08-29
---

## 62. Camb AI TTS reproduce audio duplicado por re-emisión de la respuesta final acumulada

**Severidad:** Media
**Componente:** `kateto/voices/base.py`, `kateto/plugins/audio_output/camb.py`

### Descripción

Al utilizar el proveedor de TTS streaming de Camb AI con agentes conversacionales, cada respuesta se sintetizaba y reproducía dos veces seguidas en su totalidad.

### Impacto

- El usuario escuchaba cada frase del agente duplicada de principio a fin.
- Se duplicaban las llamadas a la API de Camb AI consumiendo créditos innecesariamente.

### Causa

En `kateto/voices/base.py`, `_agent_loop` transmitía frases vía streaming a medida que el LLM generaba tokens. Sin embargo, al finalizar el stream del LLM, el método volvía a emitir `final_text` (el texto completo acumulado) como un último `TextChunk`. `CambAudioOutput` recibía este bloque completo y procedía a llamar a la API de TTS una segunda vez para el mensaje entero.

**Solución aplicada:**

1. En `kateto/voices/base.py`: Si el generador ya había emitido frases intermedias (`sequence > 0`), se omite la re-emisión del texto completo `final_text` y se emite únicamente un marcador de fin sin texto redundante.
2. En `kateto/plugins/audio_output/camb.py`: Se añadió una guarda para ignorar chunks de texto vacíos o de solo espacios en blanco, evitando peticiones HTTP espurias a Camb AI.

**Archivos:** `kateto/voices/base.py`, `kateto/plugins/audio_output/camb.py`
