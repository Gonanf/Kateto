# Spec: Visual overlay "muppet cutout" (mandíbula continua por RMS)

Fecha: 2026-08-13 | Worktree: wt/visual-overlay | Fuente: spec del usuario (harness-research/docs/muppet-cutout-spec.md) + brainstorming §I

## Problem Statement

El overlay actual de Kateto (`kateto/plugins/visual_overlay/`, HTML + Datastar v1.0.2) conmuta binariamente entre `top.png` (boca cerrada) y `mouth.png` (boca abierta) al recibir `audio_output` por el WebSocket `/ws/overlay`. Ese salto entre dos frames se ve seco y poco orgánico en stream. Los VTubers usan "muppet cutout": una mandíbula recortada que se mueve de forma continua con la amplitud del audio.

## Solution

Reemplazar el par de imágenes estáticas por dos capas superpuestas (cabeza fija + mandíbula móvil) animadas por CSS transforms continuas. El evento `audio_output` del bus agrega al payload la métrica `rms` (amplitud normalizada y suavizada con EMA) y el frontend mapea ese valor a `translateY + rotate` de la capa mandíbula vía Datastar, con el pivote en la articulación mandibular. Sin plugins de OBS ni aplicaciones externas: todo por el WS existente.

Constraints del usuario:
- Las imágenes son STOCK por ahora (las elige y edita el usuario); después serán dibujadas. El runtime NO genera ni busca imágenes: consume los assets que el usuario pone en `config/voices/{name}/`.
- El TTS hoy es EdgeTTS o Boson (Zonos2 después): el RMS se calcula del PCM que se reproduce (mixer/player), no de un provider específico.

## User Stories

1. Como usuario, quiero que la boca de la vtuber se mueva de forma continua con mi voz, para que el stream se vea natural.
2. Como usuario, quiero poner mis propias imágenes (cabeza y mandíbula) sin tocar código, para customizar la vtuber.
3. Como usuario, quiero que si no hay imágenes segmentadas, el overlay siga funcionando con el par viejo, para no romper el stream.
4. Como desarrollador, quiero que el evento audio_output lleve rms, para que cualquier cliente pueda animar.
5. Como usuario, quiero que la boca no vibre con el ruido de fondo, para que el movimiento sea suave.

## Implementation Decisions

- **Activos**: `avatar_head.png` + `avatar_jaw.png` en `config/voices/{voice}/` (provistos por el usuario, stock por ahora). Fallback: si faltan las capas, se usa el par `top.png`/`mouth.png` actual.
- **Cálculo de RMS en backend**: sobre el PCM que se reproduce (mixer/player en audio_output): ventana 10-20ms, normalización con umbral de ruido (`clamp((rms - noise)/(peak - noise), 0, 1)`), suavizado EMA con α 0.25-0.35. El RMS viaja en el payload del evento `audio_output` por `/ws/overlay`: `{event: "audio_output", data: {rms, viseme?, is_speaking}}`.
- **Frontend**: contenedor relativo con dos `<img>` absolutas (head z-index 2, jaw z-index 1), `transform-origin: 50% 65%` en la mandíbula, y Datastar aplicando `data-style-transform="translateY(${jawOffsetY}px) rotate(${jawRotation}deg)"`.
- **Mapeo**: rms < 0.05 → 0/0; si no, `factor = clamp((rms-0.05)/0.95, 0, 1)`; `jawOffsetY = factor × 16` (rango 0-20px), `jawRotation = factor × 4.5` (rango 0-6°).
- **Compatibilidad**: el WS `/ws/overlay` mantiene el contrato; el campo `rms` es aditivo. El HTML del overlay sirve las capas por el mismo mecanismo de allowlist de assets existente.

## Testing Decisions

- Seam principal: el mapeo rms→(offset, rotation) como función pura. Seam secundario: el cálculo de RMS sobre PCM (ventana + EMA) y el payload del evento.
- Un buen test: rms 0 → 0/0; rms 0.5 → valores intermedios; rms ≥1 → máximos (16px/4.5°); el RMS con ruido por debajo del umbral queda en 0; el evento conserva el contrato viejo y suma rms.
- Prior art: tests de audio_output y del plugin visual_overlay (servir assets, allowlist).

## Out of Scope

- Generación/dibujado de las imágenes (las pone el usuario; stock por ahora, dibujadas después).
- Visemas reales (la spec acepta `viseme` opcional pero no se implementa un extractor ahora).
- Migración a Zonos2 (solo afecta de dónde sale el audio; el RMS es del PCM reproducido).

## Further Notes

- Spec original completa del usuario: `/home/chaos/proyectos/harness-research/docs/muppet-cutout-spec.md`.
- Ver brainstorming-kateto.md §I y §D9/H12.
