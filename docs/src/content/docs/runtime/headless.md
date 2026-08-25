---
title: Runtime headless (discusiones multi-voz)
description: Cómo usar el runtime real de Kateto como harness de discusión multi-voz sin TTS.
---

# Runtime headless

El runtime de Kateto (`uv run kateto run`) puede usarse **headless** (sin micrófono ni TTS) como harness de discusión multi-voz: varias voces debaten un tema por el bus de eventos y el resultado se captura por WebSocket.

## Receta básica

1. Config sin mic/TTS activo.
2. Disparar una discusión con `POST /events/send` con el evento `generate`.
3. Escuchar el stream por `WS /events/stream`.
4. Orquestar con Jane como jueza.
5. Sincronizar por **inactividad** (N segundos sin `text_chunk` de una voz), no por `voice_idle` (solo Jane lo emite de forma fiable).

## Gotchas conocidos

- **Modelo lento + server cierra:** si el modelo piensa mucho (`reasoning_content`), el server `:11434` cierra la conexión y el cliente reintenta en loop (`Retrying request to /chat/completions`) → la voz nunca emite `text_chunk`. Subir el timeout del server o bajar `max_tokens`.
- **Estado sucio entre corridas:** si un `generate` previo no terminó, la voz queda "generando" y los siguientes eventos se acumulan sin procesar. Matar y relanzar `uv run kateto run` fresco.
- **`dept` en `GenerateData`:** el contrato rechaza `dept` por `extra_forbidden` — omitirlo (el default es `fun`).
- **IDLE_GAP:** usar ≥ 260s de gap + hard cap ≥ 560s en el cliente de captura.

Ver la receta completa en `references/runtime-headless-discussion.md` del skill de Kateto.
