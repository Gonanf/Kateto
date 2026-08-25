---
title: "Voces batch plugins acumulan estado sucio y dejan de generar tras corridas fallidas"
description: "Síntoma"
---


## Síntoma
Tras 2 corridas de captura fallidas (una donde Jane colgó emitiendo tool_call como
texto, otra con timeouts), un nuevo `generate` dirigido a doktor/conquest/jane
llegaba al bus y se dispatchaba correctamente (`emit generate target=doktor`) pero
la voz **no emitía ningún `text_chunk`**. Solo funcionó tras matar y relanzar el
runtime fresco.

## Causa raíz
Las voces son batch plugins con una `asyncio.Task` de generación (`_generation_task`
en `base.py`). Si una corrida anterior termina de forma anómala (generate colgado,
timeout del cliente, tool_call no resuelto), la task queda en estado inconsistente
y el siguiente `generate` se acumula pero no se procesa. El runtime no reinicia la
task de la voz ante `generate` mientras `_generation_task` no esté `None`.

## Impacto
El runtime parece vivo (`/voices` responde, `generate` se dispatcha) pero las voces
están mudas. Muy difícil de diagnosticar sin leer el log de `text_chunk`.

## Workaround
Matar y relanzar el runtime entre pruebas que dejen voces a medias.
