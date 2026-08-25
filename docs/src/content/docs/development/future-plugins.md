---
title: Plugins futuros
description: Features futuras de Kateto — boson.ai TTS, PNGTuber, TTS→Mic, YouTube chat, VoiceClassifier fine-tuned.
---

# Plugins futuros

Lista de features planeadas para Kateto (fuente: decisiones del usuario en blogs de discusión y la investigación de harnesses):

| Feature | Detalle |
|---|---|
| **Boson.ai TTS** | Provider TTS con voice cloning (ref_audio/ref_text) y streaming. Selector por voz (`VoiceSettings.tts_provider`), no reemplaza Zonos. |
| **PNGTuber / visual overlay** | Ya implementado como overlay lite (ver [Overlay visual](/runtime/overlay/)). PNGTuber completo queda como evolución. |
| **TTS→Mic** | Enrutar la salida TTS a un micrófono virtual (para unirse a llamadas/streams como participante). |
| **YouTube chat** | Conectar el chat en vivo de YouTube al bus de eventos (dept="fun"). |
| **VoiceClassifier fine-tuned** | Entrenar el clasificador con ventana deslizante de transcripciones reales (no ideas unidas, no chunks sueltos). |

Para la lista completa de voces futuras: [voice-list-future](/voices/voice-list-future/).

Fuente original: `~/proyectos/Blogs/kateto-features-para-opencode.md`.
