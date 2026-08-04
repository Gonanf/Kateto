---
id: 39
title: ClassifierExecutor no recibe 'transcription' del whisper (dispatch bug)
status: open
severity: high
date: 2026-07-25
---

## Síntoma
En un run real (whisper turbo-q5 en `:8090`, LLM en `:11434`), el pipeline
`audio_chunk → whisper → transcription → classifier → generate → voice` se corta
en el classifier: el `ClassifierExecutor.on_transcription` **no se ejecuta**
cuando el `transcription` viene del whisper, aunque el evento SÍ llega a los
`VoiceAgent` (mismos suscriptores).

Evidencia aislada con `script/qa/debug4.py`:
- Emitir `transcription` **manualmente** → el classifier ejecuta `on_transcription`
  y emite `error` (MalformedUpstreamResponse, esperado porque el modelo con el
  system prompt genérico no devuelve el schema `category`).
- Emitir `audio_chunk` (whisper real) → el whisper transcribe y emite
  `transcription`, los `VoiceAgent` responden (`voice_status` WAITING→IDLE) pero
  el classifier **no emite nada** (ni `classification` ni `error`); el
  `wait_for_idle` se cuelga (actividad continua).

`get_event_registrations()` confirma que `executor_classifier` está suscrito a
`transcription`. El handler está registrado pero el evento del whisper no llega
a él en runtime.

## Hipótesis (raíz)
`ClassifierExecutor.initialize` hace:

```python
manager.register_event("transcription", TranscriptionData)
```

solo registra el **contrato** y depende del auto-discovery
`Plugin.iter_event_handlers()` (en `core/plugin.py`) para suscribir
`on_transcription` durante `PluginManager.enable_plugin`
(`core/manager.py`, líneas ~67-84). El `VoiceAgent` usa el mismo mecanismo y
funciona, por lo que el bug está en cómo se resuelve/despacha el suscriptor en
el path del whisper específicamente:

- Orden de enable/suscripción: el classifier puede suscribirse antes de que el
  whisper emita, o el worker del classifier no levanta a tiempo.
- Source filtering en `_resolve_subscribers` (`core/manager.py`, ~320-338):
  `source_plugin = envelope.source.split("/")[0]`; el whisper emite
  `source="audio_processor_whisper"`, el classifier es `executor_classifier`,
  no debería filtrar, pero vale la pena verificar el `target` real del emit
  del whisper (`kateto/plugins/audio_processor/whisper.py` línea 45:
  `emit("transcription", transcription, source=self.name)` — sin target).

## Pasos para reproducir
```bash
cd /home/chaos/proyectos/OpenaiBuildWeek/Kateto
rm -rf script/qa/__pycache__
timeout 160 uv run python script/qa/debug4.py
cat script/qa/run4/debug4.log
# Con transcription manual -> aparece 'error' del executor_classifier.
# Con audio_chunk (whisper) -> NO aparece 'error' ni 'classification' del classifier.
```

O el e2e completo:
```bash
timeout 200 uv run python script/qa/e2e_real_audio.py
# wait_for_idle hace WARN timeout; no hay [OK] Classification ni [OK] Generation.
```

## Impacto
Bloquea todo el pipeline de decisión: sin classifier no hay `generate`, sin
`generate` no hay voz. El sistema no funciona end-to-end con audio real.

## Fix sugerido
Asegurar que el handler `on_transcription` del `ClassifierExecutor` quede
suscrito de forma explícita y robusta (no solo vía auto-discovery del contrato),
p. ej. registrar el handler como hace el `VoiceAgent`, o verificar que
`enable_plugin` realmente despache a todos los suscriptores del evento
independientemente del emisor. Verificar también que el worker del classifier
esté vivo antes de que el whisper emita.

## Estado
Sin resolver. OpenCode fue delegado para el fix pero timéo a los 600s sin
completar. Pendiente de fix + verificación con `script/qa/e2e_real_audio.py`.
