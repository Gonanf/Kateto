---
title: "voice_idle solo se emite de forma fiable por jane; doktor/conquest no"
description: "Síntoma"
---


## Síntoma
En una discusión multi-voz, el log mostró solo 1 evento `voice_idle` (de jane).
doktor y conquest generaron sus `text_chunk` pero no emitieron `voice_idle` al
terminar.

## Causa raíz
`VoiceAgent._stream_response` emite `voice_idle` en su `finally` (base.py:587).
Pero si la voz corta por timeout del cliente / se reinicia el runtime entre
corridas, o si el `generate` llega mientras la voz está en estado "speaking"
colgado, el `finally` no se alcanza limpiamente y no hay `voice_idle`.

## Impacto
Un orchestrator externo que sincroniza por `voice_idle` se cuelga esperando. La
sesión tuvo que sincronizar por *inactividad* (N seg sin chunks) en vez de por
`voice_idle`.

## Workaround
Sincronizar consumidores por inactividad de `text_chunk`, no por `voice_idle`.
