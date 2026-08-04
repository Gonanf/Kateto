---
id: 41
title: Modelo por defecto "Kateto" (Bonsai-8B-Q1_0, 1-bit) inutilizable para classifier/voice
status: open
severity: high
date: 2026-07-25
---

## Síntoma
El modelo cargado por defecto bajo el alias `Kateto` en el servidor
`llama.cpp` de `:11434` es **Bonsai-8B-Q1_0** (cuantización 1-bit). Ese modelo:

- No emite token de fin (`<EOS>`) de forma fiable → genera hasta `max_tokens`
  y se cuelga.
- ~5 tok/s → un `classify` de ~32 tokens tarda ~49s, superando el
  `timeout_s=10` del `HttpProvider` → `ReadTimeout`.
- Respuestas incoherentes para clasificación/generación.

Resultado: el `ClassifierExecutor` (y el `VoiceAgent` vía `LlamaCppChatProvider`)
no pueden usar el modelo por defecto. El e2e solo avanzó usando el alias
**`KatetoTalker`** (modelo instruction-tuned capaz, ya cargado en `:11434`,
~3.4s por respuesta con EOS).

## Hipótesis (raíz)
El `config/defaults/config.toml` apunta el `executor_classifier` y el
`voice_llm` al endpoint `:11434` con `model = "Kateto"` (o sin modelo
explícito), y el server tiene `Kateto` mapeado a un GGUF 1-bit inutilizable
para tareas de decisión/generación. El modelo por defecto del server no es
adecuado para el workload de Kateto.

## Pasos para reproducir
```bash
curl -s http://127.0.0.1:11434/v1/models | python3 -m json.tool
# "Kateto" -> Bonsai-8B-Q1_0 (1-bit); "KatetoTalker" -> instruction-tuned capaz.
```

## Impacto
Con el modelo por defecto, el sistema no completa ni la clasificación ni la
generación de voz en un run real. El usuario debe cargar/aliasear un modelo
capaz (como `KatetoTalker`) para que Kateto funcione.

## Fix sugerido
- En `config/defaults/config.toml`, apuntar `executor_classifier.model` y
  `voice_llm.model` a un modelo instruction-tuned capaz (no 1-bit), o
- Documentar el requisito de modelo (instruction-tuned, emite EOS, >X tok/s)
  y validar al arranque que el modelo cargado sea apto, o
- Que el `ClassifierProvider`/`LlamaCppChatProvider` fuercen `max_tokens`
  razonable y manejen la ausencia de EOS (ya se agregó `max_tokens` a
  `ClassifierRequest`/`ChatRequest` en `providers/_models.py` durante la sesión
  de debug).

## Estado
Abierto. El e2e funciona usando `KatetoTalker` explícitamente, pero el modelo
por defecto `Kateto` (1-bit) sigue siendo inutilizable.
