---
title: "2026 08 13 Streaming Latency"
description: "Spec de implementación — 2026 08 13 Streaming Latency."
---

# Spec: Latencia de streaming (EventStream dual + TTS buffered + client reuse)

Fecha: 2026-08-13 | Worktree: wt/streaming-latency | Fuente: harness research (brainstorm-kateto.md §B1/B2/B3/G1/D1, bugs 58/59/60)

## Problem Statement

El pipeline de voz tiene latencia perceptible en tres puntos: (1) el LLM no entrega texto al TTS hasta que termina el turno completo; (2) el TTS sintetiza por token suelto (bug 60, Zonos) o arranca tarde con providers que no streamean; (3) los clientes HTTP de los providers se recrean en cada llamada (bug 59). Además el ASR transcribe por chunk, no en streaming (bug 58), atrasando todo el ciclo.

## Solution

Un `VoiceEventStream` dual: los deltas de texto del LLM se emiten en vivo (las frases completas se despachan al TTS apenas se detecta puntuación, sin esperar el fin del turno) mientras un Future resuelve el mensaje final con usage y stop reason para el bus. El TTS bufferiza por frase (un síntesis por frase, no por token). Los clientes HTTP se crean una vez por endpoint en un ProviderRegistry y se reutilizan. En fase 2, el ASR emite hipótesis parciales para que el clasificador arranque antes.

Constraint del usuario: el TTS hoy es EdgeTTS o Boson TTS; Zonos2 viene después. Todo el diseño de streaming/buffering debe ser agnóstico del provider de TTS.

## User Stories

1. Como usuario, quiero que la voz empiece a hablar antes de terminar de pensar, para que el stream se sienta vivo.
2. Como voz, quiero entregar frases completas al TTS en cuanto están listas, para reducir la latencia percibida.
3. Como desarrollador, quiero que el TTS funcione igual con EdgeTTS, Boson o Zonos2, para no atarme a un provider.
4. Como desarrollador, quiero reutilizar los clientes HTTP de los providers, para no pagar handshake en cada llamada.
5. Como usuario, quiero que la voz no suene cortada ni entrecortada, para que sea natural.
6. Como usuario, quiero que el clasificador arranque con mi frase a medio decir, para que la respuesta llegue rápido (fase 2).

## Implementation Decisions

- **VoiceEventStream**: clase asyncio que es AsyncIterator de deltas de texto y expone `final_message()` (Future con el mensaje completo, usage, stop reason). El data plane existente (token_queue) sigue igual: el stream alimenta al pipeline.
- **Segmentación por frase**: el consumidor de deltas acumula hasta un delimitador (., !, ?, \n) y despacha la frase completa al TTS. El TTS arranca con la primera frase lista; no espera el turno.
- **Buffering TTS agnóstico del provider**: la capa de audio_output recibe frases (no tokens) y las sintetiza con el provider configurado (EdgeTTS/Boson hoy, Zonos2 futuro). Para providers streaming (Zonos) se mantiene el modo incremental por frase; para providers no-streaming se encola la frase y se reproduce al recibir el audio completo.
- **ProviderRegistry**: un solo client HTTP (httpx/AsyncOpenAI) por endpoint, creado una vez y reutilizado. Config por modelo vía config existente (sin reescribir config de usuario).
- **ASR streaming (fase 2, bug 58)**: whisper emite hipótesis parciales con la ventana de VAD; el clasificador puede evaluar hipótesis preliminares. Fase 2 NO bloquea esta spec.
- **max_tokens/retries por voz** configurables (mismo cambio que prompt-consistency, no duplicar).

## Testing Decisions

- Seam principal: el VoiceEventStream y el segmentador de frases (puras). Seam secundario: el ProviderRegistry (mismo objeto devuelto para el mismo endpoint).
- Un buen test: con un faux provider que emite deltas temporizados, el primer audio se despacha antes del final del turno; frases se forman solo en delimitadores; el stream resuelve final_message con usage; el registry devuelve el mismo client para el mismo endpoint.
- Prior art: faux provider pattern (brainstorm §G4), tests de audio_output existentes.

## Out of Scope

- Streaming ASR completo (fase 2, bug 58).
- Migrar a Zonos2 (viene después; el código debe dejarlo listo sin romper EdgeTTS/Boson).
- Cambiar el contrato de eventos del bus.

## Further Notes

- Ver brainstorming-kateto.md §B1/B2/B3/G1/D1 y docs/bugs/58-60.
- La métrica RMS para el overlay (spec visual-overlay) sale del PCM reproducido; esta spec no la calcula.
