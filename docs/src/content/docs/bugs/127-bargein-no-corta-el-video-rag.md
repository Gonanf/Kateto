---
id: 127
title: "Barge-in: el video-rag y la narración que pide no se cortan cuando el usuario habla"
severity: Alta
status: resolved
component: kateto/plugins/executor/static_vision_plugin.py
resolved: 2026-09-18
---

## 127. Barge-in: el video-rag y la narración que pide no se cortan cuando el usuario habla

**Severidad:** Alta
**Componente:** `kateto/plugins/executor/static_vision_plugin.py`, `kateto/plugins/system/turn_gate.py`, `kateto/voices/base.py`, `kateto/core/event.py`

### Descripción

Al hablar encima de la narración del video-rag, el audio se cortaba (el player y las TTS sí escuchan
`interrupt`) pero el pedido al sidecar seguía corriendo y, cuando volvía, la narración hablaba igual —
como si el barge-in no hubiera existido.

### Causa

1. El plugin de visión no estaba suscrito a `interrupt`: el `describe_images` en vuelo (hasta 120 s)
   terminaba y emitía la narración igual.
2. Esa narración entraba como un `generate` sin marca de origen, así que `TurnGate.decide` la trataba
   como `"external"` — la misma prioridad que el turno del usuario: borraba `_barge_in`
   (`self._barge_in.discard(voice)`), y si no había turno activo la ejecutaba al instante, o si lo
   había la **encolaba al frente** (`front=origin == "external"`), adelantándose al turno del usuario.
3. `on_generate` hacía `self._interrupted = False` al arrancar, así que la narración borraba el estado
   de interrupción del barge-in.

### Solución aplicada

- `GenerateData.origin` (`str | None = None`): `external` (usuario/sistema), `followup` (inter-voz) o
  `ambient` (narración del video-rag). `None` = el emisor no opina y la voz resuelve el origen como
  siempre (`_followup_pending` ⇒ followup, si no external): los emisores que ya existían no cambian de
  comportamiento.
- `TurnGate.decide` con `origin="ambient"`: **DISCARD** si hubo barge-in, hay turno activo o hay
  turnos pendientes; nunca encola, nunca reclama `_active`, nunca toca `_barge_in`.
- La voz no resetea `_interrupted` cuando el origen es `ambient`.
- El plugin de visión escucha `interrupt` (sólo `voice_activity` / `user_turn`): cancela el describe en
  vuelo y sube una **época** por voz. La narración captura la época antes de pedir el describe y, si al
  volver cambió, **descarta** el resultado y reprograma el ciclo (sin emitir `generate`).

### Impacto

El usuario podía interrumpir una narración y el agente igual hablaba encima o a los segundos, sin
forma de callarlo salvo volviendo a hablar. También se rompía la prioridad del turno del usuario
(el `ambient` le borraba el estado de barge-in).

**Archivos:** `kateto/core/event.py`, `kateto/plugins/system/turn_gate.py`,
`kateto/plugins/executor/static_vision_plugin.py`, `kateto/voices/base.py`,
`kateto/tests/test_turn_gate.py`, `kateto/tests/test_vision_ocr_detect.py`
