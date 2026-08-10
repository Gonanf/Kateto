---
id: 52
title: Modelo KatetoTalker (1-bit) repite el output y es extremadamente lento
severity: medium
status: open
discovered: 2026-08-06
---

## Síntoma
Las respuestas de las voces con `model=KatetoTalker` (1-bit) venían con el párrafo
**duplicado** (el modelo reinicia y vuelve a generar el mismo texto desde el
principio, loop de contexto). Además cada voz tardaba ~90s en producir ~60 chunks.

## Causa raíz
Modelo cuantizado a 1-bit: baja coherencia y repetición; throughput muy bajo en
CPU/GPU local. El `stream=false` acumula todos los tokens (incluida la repetición)
en un único `text_chunk` final.

## Impacto
Discusiones multi-voz tardan varios minutos y requieren post-proceso para quitar
repeticiones. Inutilizable para autonomía real sin un modelo mejor.

## Workaround de la sesión
Usar un modelo con tool-calling nativo y más rápido (p.ej. Qwen) para el test de
autonomía; post-procesar repeticiones en el `.md` resultante.
