---
id: 124
title: "Visión periódica: intervalo aleatorio dentro de un rango"
severity: Media
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 124. Visión periódica: intervalo aleatorio dentro de un rango

**Severidad:** Media
**Componente:** `kateto/plugins/executor/static_vision_plugin.py` (sorteo + portón de tiempo), `kateto/plugins/executor/__init__.py` (resolución del rango por voz)

### Descripción

Pedido del usuario (textual): "lo de vídeo rag debería ser aleatorio en un
rango de tiempo".

El intervalo periódico era fijo: `vision_interval` por voz (default `"30s"`)
se registraba como job INTERVAL y disparaba exacto cada 30 s. La voz comentaba
siempre con la misma cadencia mecánica.

### Impacto

Narración ambiental predecible: el oyente aprende el ritmo y el comentario
pierde naturalidad, aunque el contenido varíe.

### Causa

Un solo valor de intervalo por voz, sin noción de rango ni sorteo entre ticks.

### Solución aplicada

1. Rango configurable por voz: `vision_interval_min` / `vision_interval_max`
   (p.ej. `"20s"` / `"90s"`). `vision_interval` queda como compatibilidad:
   sin min/max el comportamiento es el actual, exacto.
2. Mecánica: el job del scheduler se registra con el intervalo **mínimo** (es
   la granularidad del tick; sigue habiendo un solo job por voz, con ack y
   reintento como antes). En cada tick el plugin acumula tiempo y sólo narra
   cuando se alcanza el objetivo sorteado en `[min, max]` **y** pasa el portón
   de imagen repetida (que evita el costo VLM con pantalla quieta). Después de
   narrar, vuelve a sortear.
3. El sorteo se cuantiza a múltiplos del tick (`k * min`, con
   `k` uniforme en `1..max//min`): la espera real nunca baja del mínimo ni
   supera el máximo, y el log muestra la espera efectiva
   (`[vision] next jane narration in 60s (range 20-90s)`).
4. Aleatoriedad inyectable: parámetro `rng` del constructor
   (`random.Random(seed)` para tests deterministas, o callable `(1, slots) ->
   int`); el módulo `random` global nunca se toca.
5. Validación sin romper el arranque: `min > max`, valores `<= 0` o
   expresiones inválidas → warning con el valor efectivo y cadencia fija
   (`vision_interval`, default `"30s"`). Con un solo lado presente, el otro
   toma el mismo valor (fijo). `disable()` cancela igual que antes.

**Archivos:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/plugins/executor/__init__.py`, `kateto/tests/test_vision_random_interval.py`
