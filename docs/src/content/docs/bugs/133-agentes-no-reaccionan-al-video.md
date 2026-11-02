---
title: "133 — Los agentes no reaccionan al video"
description: "El describe periódico corre y escribe la descripción en la memoria de la voz, pero nada dispara un turno: el agente ve y nunca comenta."
---

**Estado:** diagnosticado, sin fix (2026-11-02) · `kateto/plugins/executor/static_vision_plugin.py`, `kateto/voices/base.py`

## Síntoma

Con `voice.<voz>.vision_periodic = true` el agente describe lo que ve cada 2–5 min
pero **nunca habla de eso**: no comenta el video, no reacciona a la cámara.

## Qué pasa de verdad (medido en el log del runtime)

Cada 2 minutos, para dionisio:

```
[scheduler] job vision-describe-dionisio target dionisio is not a receiver of
            vision_describe_request; broadcasting
[scheduler] job vision-describe-dionisio fired -> vision_describe_request
[vision] describe requester=scheduler:dionisio source=mask ...
```

Tres cosas, en orden:

1. El target no está suscripto a `vision_describe_request`, así que el scheduler
   **transmite a todos** en vez de dirigirlo. El describe igual corre.
2. El resultado sale como `vision_describe_result` (`emit_result`, línea ~919).
3. `VoiceBase.on_vision_describe_result` es un **no-op explícito**: la descripción
   sólo entra en `_event_messages`. Ningún camino emite `generate` ni
   `voice_request`, así que no hay turno y no hay voz.

O sea: la visión funciona como memoria, no como estímulo. El agente "ve" y se
queda callado por diseño, no por falla del modelo.

## Qué falta para que reaccione

Un disparador después del resultado, en un solo lugar (no en cada voz): quien
recibe `vision_describe_result` de un job periódico emite un `voice_request` con
la descripción como contexto, y el turno normal hace el resto (LLM → piper → PCM).

Cuidado con el volumen: con `audio_output_player` habilitado el comentario sale
por los parlantes del escritorio, así que el intervalo (`vision_interval_min/max`)
es lo que decide cuánto habla sin que nadie le pregunte.

## Verificación que sirve

No alcanza con ver `[vision] describe` en el log: eso sólo prueba que se miró.
Para probar que reaccionó tiene que aparecer un `[llm-chunk] voice=<voz>` a
continuación del describe, y el PCM correspondiente.
