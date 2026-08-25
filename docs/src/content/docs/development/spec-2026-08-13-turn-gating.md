---
title: "2026 08 13 Turn Gating"
description: "Spec de implementación — 2026 08 13 Turn Gating."
---

# Spec: Gating de turno + Steering/Follow-up + Barge-in

Fecha: 2026-08-13 | Worktree: wt/turn-gating | Fuente: harness research (brainstorm-kateto.md §A8/H2/G5/H8)

## Problem Statement

Kateto produce respuestas duplicadas y voces que se pisan: cada `generate` dispara al LLM aunque el mixer ya esté reproduciendo otra voz, el clasificador dijo IGNORE, o ya haya un turno en vuelo. El barge-in (el usuario interrumpe hablando) no corta de forma fiable la generación ni el audio en curso, y el `request_generation` inter-voz puede interrumpir a una voz que está a mitad de respuesta.

## Solution

Un estado de turno por voz (idle/thinking/speaking) alimentado exclusivamente por eventos del bus existente, que actúa de gate antes de cada llamada al LLM: si el mixer está ocupado, hay turno en vuelo, el clasificador dijo IGNORE o la voz está en latch de barge-in, no se llama al modelo. La interrupción del usuario (Steering) tiene prioridad inmediata y aborta el stream; los pedidos inter-voz (Follow-up) se procesan solo cuando la voz activa terminó y el usuario no está interviniendo.

## User Stories

1. Como usuario, quiero que solo una voz hable a la vez, para que el stream no sea un quilombo.
2. Como usuario, quiero que mi voz corte a la voz que está hablando, para poder interrumpir naturalmente.
3. Como voz, quiero no generar si otra voz ya está hablando, para no superponerme.
4. Como voz, quiero procesar un pedido de otra voz después de terminar mi turno, para colaborar sin pisarme.
5. Como usuario, quiero que un ruido de fondo no dispare respuestas duplicadas, para que la charla fluya.
6. Como desarrollador, quiero que el gating use los eventos del bus como única fuente de verdad, para no duplicar estado global.

## Implementation Decisions

- **VoiceTurnState por voz** (idle/thinking/speaking), actualizado por suscripción a eventos existentes: `speak`, `audio_output`, `voice_idle`, `interrupt`, `transcription`. No se crea un singleton global nuevo: el estado es derivable del bus (es el "Signals" de Kateto, pero sin duplicar mecanismos).
- **Gate de turno**: en el camino `generate -> voz`, antes de llamar al LLM, se consulta: ¿mixer ocupado? ¿turno en vuelo? ¿clasificador IGNORE? ¿voz en latch de barge-in? Si alguna condición bloquea, el `generate` se encola como Follow-up o se descarta según política.
- **Colas duales**:
  - Steering: VAD detecta habla del usuario durante la generación → `asyncio.Event` de aborto del stream de la voz activa + el nuevo mensaje se inyecta como prioridad antes del siguiente turno.
  - Follow-up: `request_generation` inter-voz se encola y se procesa cuando la voz activa terminó de hablar y el usuario no intervino.
- **Barge-in real**: VAD habla humana → interrupt del LLM stream (cancelar la generación en curso) + stop del TTS/playback + latch de barge-in en la voz. La voz interrumpida no retoma sola; espera el próximo generate.

## Testing Decisions

- Seam principal: el gate como función de decisión pura (estado del bus -> decide ejecutar/encolar/descartar). Seam secundario: los handlers de eventos de turno.
- Un buen test: dos `generate` seguidos a la misma voz mientras el mixer está ocupado producen una sola respuesta (la segunda se encola o descarta); un `interrupt` en medio de un stream cancela la generación y el TTS; un follow-up no interrumpe una voz hablando.
- Prior art: tests existentes de event_bus y del Interrupt Executor.

## Out of Scope

- Cambiar el contrato de eventos del bus.
- Rediseñar el VoiceManager (probabilidades de voz).
- Mejoras al clasificador.

## Further Notes

- Los eventos `interrupt`/`interject` ya existen (§3 Interrupt Executor); esta spec formaliza el gating y las colas, no crea un bus nuevo.
- Ver brainstorming-kateto.md §A8/H2/G5/H8.
