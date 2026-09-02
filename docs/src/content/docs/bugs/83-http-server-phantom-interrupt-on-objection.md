---
id: 83
title: "Interrupción fantasma en http_server silenciando la objeción entrante"
severity: Crítica
status: resolved
component: kateto/plugins/system/http_server.py
resolved: 2026-09-01
---

## 83. Interrupción fantasma en http_server silenciando la objeción entrante

**Severidad:** Crítica
**Componente:** `kateto/plugins/system/http_server.py`

### Descripción

Durante el debate, exactamente en la objeción de Conquest a las `15:52:22`, el orador que objeta no pronunció ninguna palabra en el TTS, y los turnos subsiguientes quedaron silenciados o encolados.

### Causa

En `kateto/plugins/system/http_server.py` existía un hook obsoleto en el relay WebSocket de la sala del juzgado (`ws/courtroom`):
```python
if parsed.get("phase") == "objection":
    await self._manager.emit("interrupt", InterruptData(reason="objection"), source="http_server")
```
Al iniciarse la objeción:
1. `bate_debate` emitía el `TextChunk` con la objeción de Conquest a las `15:52:22.987`.
2. A través del callback `on_speak`, se enviaba un mensaje WebSocket al frontend para actualizar la UI del tribunal con `phase: "objection"`.
3. Un milisegundo después (`15:52:22.988`), `http_server` recibía su propio mensaje WebSocket reflejado y emitía un nuevo evento `interrupt` en el bus.
4. Este `interrupt` fantasma cortaba de raíz la objeción de Conquest en el milisegundo en que comenzaba, silenciándolo antes de que saliera la primera muestra de audio y dejando a `TurnGate` en estado de barge-in con bloqueo de cola.

### Solución aplicada

Se eliminó la emisión de `interrupt` en el relay WebSocket de `kateto/plugins/system/http_server.py`. La orquestación del ciclo de vida del debate (`orchestrator.py`) es la única autoridad que gestiona el corte de audio en el punto exacto de la objeción (`_find_interruption_cue`). El servidor HTTP se limita a transmitir el estado visual sin interferir en el bus de eventos de voz.

**Archivos:** `kateto/plugins/system/http_server.py`
