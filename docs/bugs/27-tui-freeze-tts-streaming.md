---
id: 27
title: "TUI se congela durante streaming de TTS y eventos de audio"
severity: Crítica
status: resolved
component: kateto/plugins/system/tui.py, kateto/plugins/audio_output/edgetts.py, kateto/providers/edgetts.py
resolved: 2026-07-20
---

## 27. TUI se congela durante streaming de TTS y eventos de audio

**Severidad:** Crítica
**Componente:** `kateto/plugins/system/tui.py`, `kateto/plugins/audio_output/edgetts.py`, `kateto/providers/edgetts.py`

### Descripción

La TUI se congela completamente cuando cualquier plugin produce eventos de streaming — edge-tts, audio output, o cualquier fuente de alta frecuencia. El UI deja de renderizar, el cursor no responde, y el terminal se vuelve no interactivo hasta que el streaming termina.

### Impacto

- La TUI es inutilizable durante reproducción de audio
- El usuario no puede interactuar con tabs, plugins, o eventos mientras TTS está activo
- Se pierde la capacidad de interrumpir o controlar la sesión en vivo

### Causa (Root Cause Analysis)

Tres causas encadenadas, todas contribuyendo al bloqueo del event loop de asyncio:

#### Causa 1: Event observer ejecuta trabajo pesado en cada evento

`_observe_event` en `tui.py` se registra como observer del PluginManager. Se ejecuta **sincrónicamente** para cada evento en el event bus. En el path anterior a la corrección:

```python
def _observe_event(self, envelope):
    self._record_event(envelope)          # append a deque + ListView
    is_streaming = isinstance(...)
    if not is_streaming:
        self._refresh_view_after_event()  # rebuild 6 widgets
    # ... más isinstance checks, string ops, widget queries
```

Cada `audio_output` event (había uno por cada 8KB de PCM) disparaba:
1. `_record_event` → `self._events.append()` + `ListView.append(ListItem(Label(...)))` + `_format_event` → `model_dump_json()` + isinstance checks
2. `_refresh_view_after_event` → `_refresh_view` → **rebuild 6 widgets pesados** (plugin list con remove_children/mount, 3 trees con clear/add, 2 static updates)

Con edge-tts produciendo ~12 eventos/segundo (8KB chunks a 24kHz), esto saturaba el event loop.

#### Causa 2: EdgeTTS emitía un AudioOutput por cada chunk de 8KB

En `providers/edgetts.py`:
```python
_CHUNK_SIZE = 8192  # ~170ms PCM at 24000Hz s16le mono
```

Cada yield del provider creaba un `AudioOutput` event que iba al player plugin. Cada evento disparaba:
- `PluginManager.emit()` → crea asyncio.Task para cada subscriber
- `AudioOutputPlayer.on_audio_output()` → `_validate_pcm()` + `stream.write(data.samples)`
- El observer de la TUI procesaba el evento

Resultado: ~12 dispatches/segundo, cada uno creando tasks y ejecutando observer.

#### Causa 3: `_refresh_view` reconstruía árboles completos en cada ciclo

`_populate_voice_tree()`, `_populate_workflow_tree()`, `_populate_event_tree()` hacen `tree.clear()` + reconstrucción completa de nodos + `tree.root.expand_all()`. Estos son DOM operations pesados en Textual que bloquean el render loop.

### Intentos Fallidos

#### Intento 1: Filtrar eventos del observer (parcialmente efectivo)

```python
_NOISY_EVENTS = frozenset({"audio_output", "audio_output_status", "text_chunk"})
def _observe_event(self, envelope):
    if envelope.name in self._NOISY_EVENTS:
        return  # skip entirely
```

**Resultado:** La TUI dejó de agregar eventos de audio a la lista, pero seguía congelándose. El observer todavía ejecutaba `_update_voice_status` y `_update_audio_status` antes del filter, y el manager seguía creando tasks para dispatch.

#### Intento 2: Aumentar chunk size de 8KB a 64KB

```python
_CHUNK_SIZE = 65536  # ~1.4s PCM at 24000Hz s16le mono
```

**Resultado:** Menos eventos por segundo (~1.5 en vez de ~12), pero la TUI seguía congelándose porque `_refresh_view` seguía reconstruyendo widgets en cada evento no-streaming.

#### Intento 3: Buffer completo de PCM en el plugin (parcialmente efectivo)

```python
async def _emit_pcm(self, data):
    pcm_buffer = bytearray()
    async for output in self._provider.stream_sentence(...):
        if output.samples:
            pcm_buffer.extend(output.samples)
        if output.final and pcm_buffer:
            # emit single AudioOutput with all samples
```

**Resultado:** Eliminó la granularidad de eventos del provider, pero la TUI seguía congelándose porque `_refresh_view` seguía siendo el bottleneck.

#### Intento 4: Debounce de `_refresh_view` con `call_after_refresh` (insuficiente)

```python
def _refresh_view_after_event(self):
    if self._pending_refresh:
        return
    self._pending_refresh = True
    def _do_refresh():
        self._pending_refresh = False
        self._refresh_view()
    self.call_after_refresh(_do_refresh)
```

**Resultado:** Coalesceaba eventos dentro de un solo render cycle de Textual, pero con alta frecuencia de eventos, el refresh seguía ejecutándose demasiado seguido.

### Solución Aplicada

Cambio en **tres capas**:

#### 1. EdgeTTS: Buffer completo + 2 eventos por oración

`kateto/plugins/audio_output/edgetts.py`:
- Buffer toda la PCM en memoria durante la síntesis
- Emitir UN solo `AudioOutput` con todos los samples al final
- Emitir UN `AudioOutput(final=True)` para signal finish
- **Resultado:** 2 eventos por oración en vez de ~12 por segundo

#### 2. EdgeTTS Provider: Chunk size 8KB → 64KB

`kateto/providers/edgetts.py`:
```python
_CHUNK_SIZE = 65536  # ~1.4s PCM at 24000Hz s16le mono
```
- **Resultado:** Menor overhead de I/O en ffmpeg subprocess

#### 3. TUI: Throttle de tree rebuilds a 1/segundo

`kateto/plugins/system/tui.py`:
- `_observe_event()` retorna inmediatamente para `audio_output`; `text_chunk` evita estados, historial y árboles costosos, pero continúa hacia `_handle_text_chunk()` para mantener visible la conversación
- Split `_refresh_view` en `_refresh_light()` (text fields baratos) y `_schedule_tree_refresh()` (4 trees pesados)
- `_refresh_light()` corre en cada evento — solo actualiza 3 Static widgets
- `_schedule_tree_refresh()` usa timestamp throttle: max 1 rebuild/segundo
- `_refresh_view()` preservado para acciones de usuario (submit, toggle plugin) que necesitan refresh inmediato
- **Resultado:** Los trees se reconstruyen max 1 vez/segundo sin importar la frecuencia de eventos

#### 4. TUI: Safe JSON para campos binarios

`kateto/plugins/system/tui.py`:
```python
def _safe_event_json(data):
    try:
        return data.model_dump_json(exclude_none=True)
    except Exception:
        fields = {k: f"<{type(v).__name__} {len(v)} bytes>" if isinstance(v, bytes) else v ...}
        return json.dumps(fields, default=str)
```
- **Resultado:** Elimina crashes de `PydanticSerializationError` en `AudioOutput.samples`

#### 5. Whisper: Timeout 10s → 60s

`kateto/providers/whisper.py`:
```python
timeout_s: float = 60.0  # was 10.0
```
- **Resultado:** Whisper puede procesar audio de 8+ segundos sin timeout

### Archivos

- `kateto/plugins/audio_output/edgetts.py`
- `kateto/plugins/system/tui.py`
- `kateto/providers/edgetts.py`
- `kateto/providers/whisper.py`
- `kateto/tests/test_audio_output_plugins.py`
