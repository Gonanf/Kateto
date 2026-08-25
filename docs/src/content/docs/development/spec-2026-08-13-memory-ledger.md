---
title: "2026 08 13 Memory Ledger"
description: "Spec de implementación — 2026 08 13 Memory Ledger."
---

# Spec: Memoria de 2 capas (VoiceMemoryLedger)

Fecha: 2026-08-13 | Worktree: wt/memory-ledger | Fuente: harness research (brainstorm-kateto.md §D5/H3/G3)

## Problem Statement

La memoria persistente de Kateto es pobre y desorganizada: los recuerdos se inyectan sueltos en el SOUL o se escriben en caliente (voice_soul_manager muta SOUL.md/JOURNAL.md sin validación ni rollback fiable), degradando la consistencia de la voz y ensuciando el estado entre corridas. No hay hechos declarativos por voz que persistan de forma estructurada entre streams.

## Solution

El SOUL queda de solo lectura. Cada voz tiene un **VoiceMemoryLedger**: un almacén estructurado y tipado (hechos, relaciones, patrones de acción) con escritura atómica, validación Pydantic y snapshots reversibles. Al inicio de sesión, el ledger se inyecta como bloque compacto `<VOICE_MEMORY>` después del SOUL (snapshot congelado) y NO se re-inyecta a mitad de sesión. Las voces pueden escribir memoria vía una tool `refine_memory(fact, category, evidence)` con trazabilidad y rollback. En una fase posterior, una capa episódica autogenera pares Q/A con un modelo barato y los persiste en un sink vectorial (ChromaDB) para recall bajo demanda.

## User Stories

1. Como voz, quiero recordar hechos del usuario entre streams, para no preguntar dos veces lo mismo.
2. Como usuario, quiero que la voz no olvide lo que hablamos la semana pasada, para tener continuidad.
3. Como voz, quiero guardar una memoria sin tocar mi SOUL, para no perder mi personalidad.
4. Como desarrollador, quiero que la escritura de memoria sea atómica y validada, para no corromper el estado.
5. Como desarrollador, quiero poder revertir una memoria que rompió la voz, para recuperar rápido.
6. Como voz, quiero que la memoria de proyectos (management) y la de stream (fun) estén separadas, para no mezclar contextos.
7. Como usuario, quiero que la voz use la memoria sin que su prompt se vuelva un despelote, para que siga respondiendo natural.

## Implementation Decisions

- **SOUL readonly**: voice_soul_manager deja de mutar SOUL.md en caliente; las memorias van al ledger. El SOUL solo cambia entre sesiones vía snapshot versionado (ZODB existente).
- **VoiceMemoryLedger**: almacén JSON/SQLite por voz con colecciones tipadas: `facts` (hechos confirmados), `relationships` (dinámica entre voces), `action_patterns` (comandos/scripts recurrentes). Escritura atómica con lock (patrón fcntl ya usado en Hermes) y validación Pydantic antes de escribir.
- **Inyección**: bloque `<VOICE_MEMORY>` compacto inyectado una vez al inicio de sesión, después del SOUL. Nada de re-inyección mid-session (rompe caching y consistencia).
- **Tool `refine_memory(fact, category, evidence)`**: permite a la voz agregar/actualizar/borrar memorias con snapshot antes/después y rollback si la validación falla. Replace/remove por substring corto único.
- **Scoping por departamento**: `fun` comparte memoria de stream; `work`/`management` comparten memoria de proyectos (Doktor/Conquest).
- **Capa episódica (fase 2)**: tarea auxiliar con modelo barato (no la voz principal) genera 3-5 pares Q/A de la conversación reciente cada N turnos → ChromaDB como SinkPlugin del bus; recall vía tool bajo demanda, no inyectado.

## Testing Decisions

- Seam principal: el ledger (CRUD con validación y rollback) como unidad testeable sin bus. Seam secundario: la inyección del bloque en el ContextBuilder.
- Un buen test: agregar/reemplazar/borrar una memoria con substring único; escritura concurrente no corrompe; una memoria inválida dispara rollback al snapshot previo; el bloque inyectado al inicio de sesión es estable durante la sesión.
- Prior art: tests de storage.py (VoiceFileStore) y de config.

## Out of Scope

- Base de datos vectorial en esta fase (queda la tool + el sink para fase 2).
- Migración de memorias existentes de voz.
- Compresión de contexto.

## Further Notes

- Regla de higiene (lección Hermes): guardar hechos declarativos, NO "fixed X"/PR numbers/logs de progreso.
- Ver brainstorming-kateto.md §D5/H3/G3.
