---
title: "text_chunk de una voz se dispatcha también a las otras voces (source incorrecto en routing)"
description: "Síntoma"
---


## Síntoma
Al emitir `text_chunk` desde una voz, el log muestra:
`emit text_chunk source=jane target=*` → `dispatch text_chunk to ['conquest', 'doktor']`.
El `source` es correcto (jane) pero el dispatch incluye a voces que no deberían
recibir el chunk de otra voz en el bus de eventos (solo debería ir a observers
globales / audio_output).

## Causa raíz
El `text_chunk` se emite con `target=*` (broadcast). Las voces son subscribers de
`text_chunk` (para interjecciones / memoria), así que cada voz recibe los chunks de
las otras. No es un bug de `source` sino de fan-out: un chunk de habla de una voz
no debería entregarse como `text_chunk` a las otras voces como si fuera suya.

## Impacto
Consumo innecesario y posible confusión en observers (p.ej. un cliente WS que filtra
por `source` está bien, pero cualquier plugin que actúe sobre `text_chunk` ajeno se
dispara por error).

## Workaround
Filtrar en el consumidor por `envelope.source == voz_esperada` (lo hizo el cliente
de captura de la sesión).
