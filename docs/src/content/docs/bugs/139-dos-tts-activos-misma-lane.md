---
id: 139
title: "Dos plugins TTS prendidos sintetizan la misma frase en la misma lane (dos sample rates)"
severity: Media
status: resolved
component: kateto/plugins/audio_output/player.py
resolved: 2026-11-08
---

## 139. Dos TTS prendidos sintetizan la misma frase en la misma lane

**Severidad:** Media
**Componente:** `kateto/plugins/audio_output/` (piper, edgetts) + `~/.config/kateto/config.toml`

### Descripción

Con `[plugin.audio_output_edgetts] enabled = true` **y** `[plugin.audio_output_piper]
enabled = true`, cada frase se sintetizaba dos veces y las dos versiones caían en la
misma lane de audio de la voz.

### Impacto

Audio duplicado/entrecortado: se oía la frase dos veces, con dos sample rates
distintos (piper 22050 Hz, edge 24000 Hz) escritos en la misma lane, forzando
reabrir el stream entre chunks.

### Causa

Ningún plugin TTS mira `voice.<id>.tts_provider`: todos los que estén `enabled`
se suscriben a `text_chunk`. El campo `tts_provider` sólo se usa en
`voices/base.py` para elegir el audio de referencia de Zonos — no enruta la síntesis.
El player arma una lane por `voice_id`, así que las dos síntesis se concatenan.

### Solución aplicada

Config: `[plugin.audio_output_edgetts] enabled = false` (las voces usan
`tts_provider = "piper"`), con comentario explicando el motivo.

### Verificación observada

Corrida con un solo TTS prendido: `[piper] synth start` 1 vez por voz
(`dionisio`, `elchacal`, `pagliacci`), `edgetts` ausente, **1** apertura de stream
(sin cambios de rate), 0 `Traceback`/`ERROR`, 4 impulsos hablados.

**Pendiente (no resuelto acá):** si alguna vez se quieren dos TTS activos a la vez,
el enrutado por `tts_provider` tiene que existir en el bus (hoy no existe).

### Archivos

`~/.config/kateto/config.toml`
