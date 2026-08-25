---
title: Plugins
description: Vista general de los plugins del bus de eventos de Kateto.
---

# Plugins

Cada plugin de Kateto vive en `kateto/plugins/<tipo>/` y se auto-descubre por convención: un archivo `__init__.py` que exporta `create_plugins(ctx)` instancia el plugin, y los métodos `on_*` se registran como suscriptores del bus.

## Tipos de plugin

| Directorio | Responsabilidad |
|---|---|
| `audio_input/` | Captura de micrófono, VAD (Silero), segmentación |
| `audio_processor/` | Transcripción Whisper |
| `audio_output/` | TTS (EdgeTTS/Boson, futuro Zonos2), playback PCM |
| `connector/` | CLI allowlist, Google Calendar/Meet |
| `executor/` | Classifier (intención), Interrupt, TODO, Backlog |
| `system/` | HTTP server, MCP server, VoiceManager, overlay visual |

## Contratos

Cada evento tiene un modelo Pydantic (frozen, strict — `EventModel` en `core/event.py`). El envelope es `EventEnvelope(name, data, source, timestamp, target, capabilities, only_once)`.

## Ver también

- [Audio input](/plugins/audio-input/)
- [Audio processor](/plugins/audio-processor/)
- [Audio output](/plugins/audio-output/)
- [Executors](/plugins/executors/)
- [Voice Manager](/plugins/voice-manager/)
- [System](/plugins/system/)
- [Connectors](/plugins/connectors/)
