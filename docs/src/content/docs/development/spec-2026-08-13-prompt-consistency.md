---
title: "2026 08 13 Prompt Consistency"
description: "Spec de implementación — 2026 08 13 Prompt Consistency."
---

# Spec: Prompt estable + SOUL caching por voz

Fecha: 2026-08-13 | Worktree: wt/prompt-consistency | Fuente: harness research (brainstorm-kateto.md §A1/A2/G2/H1/D2)

## Problem Statement

Las voces de Kateto (Jane, Doktor, Conquest, Whisperer) responden de forma inconsistente: el system prompt (SOUL) se arma de nuevo en cada turno mezclando personalidad, herramientas y contexto volátil, lo que invalida cualquier caché de prefijo del LLM y encarece/lentece cada llamada. Además, la mutación del SOUL a mitad de conversación (voice_soul_manager escribe SOUL.md en caliente) produce deriva de comportamiento y respuestas impredecibles.

## Solution

Cada voz construye su system prompt UNA vez al spawnearse, con un prefijo estrictamente estable (SOUL + capabilities + guidance fijo) y todo el contexto volátil (memoria, historial, estado) al final de la estructura de mensajes. El prefijo estable se reutiliza byte a byte en cada turno para maximizar el prompt caching del provider (llama.cpp, DeepSeek, etc.). El SOUL es inmutable durante la conversación; cualquier cambio se versiona y se aplica entre sesiones, nunca en caliente.

## User Stories

1. Como voz, quiero que mi personalidad (SOUL) no cambie a mitad de conversación, para responder de forma estable durante todo el stream.
2. Como usuario, quiero que las voces tengan un tiempo al primer token bajo, para que la respuesta no se sienta lenta.
3. Como usuario, quiero que el costo de tokens de las voces baje, para poder correr streams largos sin gastar de más.
4. Como voz, quiero ver solo el contexto relevante (memoria, historial reciente) al final de mi prompt, para no distraerme con ruido.
5. Como desarrollador, quiero un único módulo que arme el prompt de cada voz, para poder tunear consistencia en un solo lugar.
6. Como desarrollador, quiero que el clasificador y los resúmenes de fondo no desalojen el caché del SOUL de las voces activas.
7. Como voz, quiero que mis herramientas (capabilities) estén declaradas de forma estable, para no perder acceso a ellas a mitad de conversación.

## Implementation Decisions

- **ContextBuilder por voz**: módulo único que arma el contexto LLM de cada voz en secciones ordenadas: `[SOUL estable] -> [Tool schemas] -> [Memoria durable] -> [Historial reciente] -> [Contexto volátil]`. Toda generación de prompt pasa por él.
- **Prompt congelado por spawn**: el system prompt se construye una sola vez al crear la VoiceAgent (SOUL + capabilities + guidance). El rebuild solo ocurre ante compresión de contexto o entre sesiones, nunca por turno.
- **SOUL de solo lectura durante la sesión**: voice_soul_manager y cualquier mutación escriben a un snapshot versionado (ZODB existente) que se aplica en el próximo spawn; la voz viva nunca ve su SOUL cambiar.
- **Prompt caching**: `prompt_cache_key` fijo por voz (`kateto-voice-<voice_id>`) + headers de sesión (`x-session-id`, `x-session-affinity`) en los providers OpenAI-compatibles que lo soporten. Requests de fondo (clasificador EXECUTE/IGNORE, resúmenes) usan cache off o namespace distinto.
- **Config por voz**: `max_tokens`, retries y timeout configurables por voz en config (hoy hardcodeados en código), respetando la config de usuario existente (tomllib, sin reescribir).

## Testing Decisions

- Seam principal: el ContextBuilder (función pura de construcción de prompt). Seam secundario: el factory de voces.
- Un buen test verifica comportamiento externo: el prompt de una voz tiene el mismo prefijo estable en turnos consecutivos aunque el contexto volátil cambie; el SOUL no se muta en caliente; el cache key es estable.
- Prior art: tests existentes de voices/factory y de config.

## Out of Scope

- Migración a otro LLM provider.
- Compresión de contexto (spec separada, ver brainstorming §H6).
- Cambiar el formato de los SOUL.md existentes.

## Further Notes

- Constraint del usuario: hoy las voces usan EdgeTTS o Boson TTS (Zonos2 vendrá después) — esto no afecta al prompt, pero el caching del TTS no es parte de esta spec.
- El voice_manager y el clasificador NO cambian su contrato de eventos.
- Ver brainstorming-kateto.md §A1/A2/G2/H1 para la fundamentación.
