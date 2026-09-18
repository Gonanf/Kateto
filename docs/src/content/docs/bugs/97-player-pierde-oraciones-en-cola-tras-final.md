---
id: 97
title: "Player pierde oraciones completas sintetizadas cuando la síntesis adelanta al playback"
severity: Crítica
status: resolved
component: kateto/plugins/audio_output/player.py
resolved: 2026-09-17
---

## 97. Player pierde oraciones completas sintetizadas cuando la síntesis adelanta al playback

**Severidad:** Crítica
**Componente:** `kateto/plugins/audio_output/player.py`

### Descripción

Turno de Jane con 3 oraciones: la 1 y 2 sonaron, la 3 ("Por favor, dime de qué video se trata", 127872 bytes totalmente sintetizados y encolados) **jamás sonó**. El log del player mostraba playback completo y continuo de todo lo demás, sin interrupts ni errores: la pérdida era silenciosa.

### Impacto

Oraciones enteras descartadas de forma silenciosa; se percibe como "se corta" o "se salta partes". Ocurre casi siempre porque la síntesis por red (~3x realtime) inevitablemente adelanta al playback.

### Causa

Una sola lane por voz (`_raw_lanes[voice]`): los chunks de la oración N+1, ya encolados, quedaban **detrás** del sentinel `final/None` de la oración N en la misma cola. Al consumir el sentinel, el mixer hacía `_pop_lane` y huérfana la cola con los chunks de N+1 dentro; los `final` de N+1 encontraban la lane inexistente y se descartaban. Nada volvía a registrar la voz.

### Solución aplicada

Lanes por oración (`voice`, `voice#2`, …): una vez que una lane recibe su `final`, el audio nuevo abre una lane fresca encolada **detrás** (el mixer drena en orden de inserción). Mapeo `lane → voz` para visemes/`_playing_speaker`/interrupts por `dept`, y `audio_ms` correctamente relativo a cada oración. Opcionalmente se aprovechó para logs de chunking `[player] queued/played/lane open/lane done/stream open|close/interrupt`.

**Regresión:** `test_player_plays_sentence_queued_behind_draining_final` (falla en el código viejo, pasa en el nuevo).

**Archivos:** `kateto/plugins/audio_output/player.py`, `kateto/tests/test_word_sync.py`
