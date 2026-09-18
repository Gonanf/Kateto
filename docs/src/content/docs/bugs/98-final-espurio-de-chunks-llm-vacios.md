---
id: 98
title: "Chunks LLM vacíos de fin de turno generaban un `final seq=0` espurio en la lane"
severity: Baja
status: resolved
component: kateto/plugins/audio_output/edgetts.py
resolved: 2026-09-17
---

## 98. Chunks LLM vacíos de fin de turno generaban un `final seq=0` espurio en la lane

**Severidad:** Baja
**Componente:** `kateto/plugins/audio_output/edgetts.py`

### Descripción

Cada turno LLM termina con un `TextChunk(text="", final=True)`. `EdgeTTSAudioOutput.on_text_chunk` emitía por él un `AudioOutput(final=True, sequence=0)` sin contenido: un sentinel extra con secuencia 0 en medio del tráfico real (visible en logs como `[player] final ... seq=0`).

### Impacto

Ruido en logs y sentinel fuera de orden que podía partir lanes (ver bug 97); benigno en la práctica pero mina de tiempo.

### Causa

La rama `if not raw_text` emitía un `final` "por si acaso", innecesario en ambos modos (stream: cada frase ya emite su propio final; buffer: con texto vacío no hay nada que flushear).

### Solución aplicada

Descartar chunks vacíos al inicio (`if not raw_text: return`).

**Regresión:** `test_edgetts_plugin_drops_contentless_chunks`.

**Archivos:** `kateto/plugins/audio_output/edgetts.py`, `kateto/tests/test_word_sync.py`
