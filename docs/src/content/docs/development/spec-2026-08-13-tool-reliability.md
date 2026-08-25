---
title: "2026 08 13 Tool Reliability"
description: "Spec de implementación — 2026 08 13 Tool Reliability."
---

# Spec: Confiabilidad de tools (guardia de truncamiento + preflight + faux provider)

Fecha: 2026-08-13 | Worktree: wt/tool-reliability | Fuente: harness research (brainstorm-kateto.md §A6/G6/G4)

## Problem Statement

El tool-calling de las voces es frágil: cuando el LLM corta por límite de tokens (`stop_reason == "length"`), los argumentos JSON de los tool calls pueden venir truncados o malformados y Kateto los ejecuta igual, produciendo comandos Shell/FileSystem corruptos y errores crípticos. No hay validación de argumentos antes de invocar, y los tests del pipeline dependen de modelos reales (lentos y caros).

## Solution

Antes de ejecutar cualquier tool call, una guardia verifica el stop reason de la respuesta: si fue `length`, los tool calls de ese turno NO se ejecutan y se devuelve al modelo un error estructurado pidiendo reintentar. Los argumentos se sanitizan y validan contra el esquema (Pydantic) antes de invocar la función destino. Las tools que cierran la tarea pueden marcar `terminate: true` para evitar un round-trip innecesario al LLM. Para testear todo esto sin LLM real, un FauxProvider simula respuestas completas (streaming, thinking, tool calls, errores) de forma determinista.

## User Stories

1. Como usuario, quiero que una respuesta truncada del LLM no ejecute comandos a medias, para que no se rompa nada.
2. Como voz, quiero que me avisen cuando mis argumentos de tool estén corruptos, para poder reintentar bien.
3. Como desarrollador, quiero validar los argumentos de las tools antes de ejecutarlas, para tener errores claros.
4. Como desarrollador, quiero testear el pipeline completo sin modelos reales, para que los tests sean rápidos y baratos.
5. Como voz, quiero no tener que decir "listo" cuando una tool ya cerró la tarea, para ahorrar un turno.

## Implementation Decisions

- **Guardia de truncamiento**: en el loop del agente (pydantic-ai harness), si la respuesta del LLM tiene `stop_reason == "length"`, marcar los tool calls del turno como inválidos; responder al modelo con un error estructurado (tipo "argumentos truncados, reintentá") y no ejecutar.
- **Preflight de tools**: antes de invocar, sanitizar strings (escapes/control chars) y validar el payload contra el schema Pydantic de la tool. Si falla, devolver error estructurado al modelo en vez de ejecutar.
- **`terminate: true`**: las tools pueden declarar que su ejecución cierra la tarea (confirmación verbal, acción final); si todas las tools de un lote terminan, no se llama al LLM de nuevo.
- **FauxProvider**: implementación de test del provider de LLM (endpoint OpenAI-compatible / pydantic-ai) que acepta un guión de pasos (`FauxResponseStep`): chunks temporizados, tool calls, errores HTTP, delays. Determinista, offline, sin API keys.
- **Toolset por departamento**: cada voz ve solo las tools que usa (fun vs management), evitando schema inflado (alineado con prompt-consistency).

## Testing Decisions

- Seam principal: la guardia de ejecución (función pura: stop reason + tool calls -> ejecutar/fallar). Seam secundario: el FauxProvider.
- Un buen test: con stop_reason length, ninguna tool se ejecuta y el modelo recibe error; argumentos malformados se rechazan con mensaje claro; un guión faux de 3 pasos (stream + tool + final) corre el pipeline completo en milisegundos sin red.
- Prior art: tests de voices/tools existentes; patrón faux provider del research (§G4).

## Out of Scope

- Cambiar el set de capabilities de las voces.
- Sandboxing de ejecución de tools (sigue siendo la validación + permisos actuales).
- Tests e2e con LLM real (los faux los reemplazan para CI; e2e reales quedan manuales/opcionales).

## Further Notes

- Ver brainstorming-kateto.md §A6/G6/G4.
- Este cambio es requisito de estabilidad para las specs de turn-gating y prompt-consistency.
