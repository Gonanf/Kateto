---
id: 64
title: "Fallo de validación Pydantic en WhisperResponse ante silencios o ruido ambiente sin habla"
severity: Media
status: resolved
component: kateto/providers/_models.py, kateto/plugins/audio_processor/whisper.py
resolved: 2026-08-29
---

## 64. Fallo de validación Pydantic en WhisperResponse ante silencios o ruido ambiente sin habla

**Severidad:** Media
**Componente:** `kateto/providers/_models.py`, `kateto/plugins/audio_processor/whisper.py`

### Descripción

Cuando el VAD detectaba un fragmento de audio con ruido ambiente o respiraciones breves y `whisper-server` retornaba `{"text":""}`, la deserialización de la respuesta fallaba con:
`ValidationError: String should have at least 1 character [type=string_too_short, input_value='', input_type=str]`.
La excepción se propagaba y silenciaba el pipeline de transcripción.

### Impacto

- Las expresiones con pausas o silencios causaban errores silenciosos en el procesador Whisper.
- El usuario hablaba al micrófono y el sistema parecía no responder.

### Causa

El modelo `WhisperResponse` en `kateto/providers/_models.py` definía `text: str = Field(min_length=1)`. Si Whisper determinaba que no había palabras audibles, el JSON contenía texto vacío, violando la restricción de longitud mínima.

**Solución aplicada:**

1. En `kateto/providers/_models.py`: Se modificó el campo a `text: str = Field(default="")`, permitiendo transcripciones vacías.
2. En `kateto/plugins/audio_processor/whisper.py`: Se agregó captura explícita de errores con logs en `on_audio_chunk`, omitiendo la emisión de eventos para transcripciones que resulten en texto vacío.

**Archivos:** `kateto/providers/_models.py`, `kateto/plugins/audio_processor/whisper.py`
