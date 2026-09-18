---
id: 99
title: "Subtítulos pelean entre texto LLM (rápido) y texto TTS (hablado): z-fighting de captions"
severity: Baja
status: open
component: kateto/plugins/visual_overlay/web/index.html, kateto/providers/edgetts.py, kateto/core/event.py
---

## 99. Subtítulos pelean entre texto LLM (rápido) y texto TTS (hablado): z-fighting de captions

**Severidad:** Baja
**Componente:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/providers/edgetts.py`, `kateto/core/event.py`

### Descripción

El caption cambia cuando llega el evento EdgeTTS, no cuando termina el subtítulo actual: el texto LLM de la oración N+1 (que llega segundos antes de ser hablada) sobrescribe el caption de la oración N en curso. Efecto de "z-fighting": ambas fuentes escriben la barra alternadamente, ganando el TTS la mayoría de las veces.

### Impacto

Subtítulos que saltan adelante y atrás respecto a lo audible. Menor desde que el audio manda (karaoke + ownership), pero persiste en los bordes de oración.

### Causa

Dos escritores sin ownership: `text_chunk` (velocidad LLM) y `audio_output.text` (velocidad TTS). Relacionado con el bug 65 (desincronización por emisión prematura de tokens).

### Posible solución

1. ✅ Aplicado (parcial): cada evento de audio lleva `text` + `words` (`WordTiming` con offsets de `WordBoundary` de EdgeTTS); el player estampa `audio_ms` de playback real en los visemes; el overlay revela karaoke sobre ese reloj y suprime captions LLM mientras hay karaoke activo.
2. ✅ Aplicado (parcial): ownership de caption por voz activa (expira 1.5s tras la última actividad audible; `interrupt`/`voice_idle` liberan).
3. Pendiente: los bordes (oración N+1 llegando antes de que N termine de sonar) aún pelean; el ownership por timeout es heurístico. Una señal de fin-de-playback real por oración (vs fin-de-síntesis) lo cerraría.

**Archivos:** `kateto/plugins/visual_overlay/web/index.html`, `kateto/providers/edgetts.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/plugins/audio_output/player.py`, `kateto/plugins/visual_overlay/visual_overlay_plugin.py`, `kateto/core/event.py`, `kateto/tests/test_word_sync.py`
