---
id: 100
title: "Warning `child process ... returncode 255` en cada teardown de ffmpeg (ruido que enmascara cortes)"
severity: Baja
status: open
component: kateto/providers/edgetts.py
---

## 100. Warning `child process ... returncode 255` en cada teardown de ffmpeg (ruido que enmascara cortes)

**Severidad:** Baja
**Componente:** `kateto/providers/edgetts.py`

### Descripción

`child process pid N exit status already read: will report returncode 255` aparece al final de casi todo turno TTS, incluso en EOF natural (`cancelled=False`). Es el `PidfdChildWatcher` de asyncio perdiendo una carrera entre el `terminate`/`wait` del `finally` de `stream_sentence` y su propio reaping.

### Impacto

Ruido que enmascara la causa real cuando SÍ hay un corte (bugs 94, 97): el 255 aparece tanto en fin natural como en cancelación por interrupt, así que no discrimina.

### Causa

Doble espera del proceso hijo en el teardown de ffmpeg de EdgeTTS.

### Posible solución

1. Evitar el `wait` redundante cuando el proceso ya terminó (chequear `returncode` bajo el mismo paso, o `try/except` alrededor del `wait` con `ProcessLookupError`/`ChildProcessError`).
2. Añadido logging `[edgetts-provider] ffmpeg end ... cancelled=... returncode=...` para distinguir fin natural de cancelación sin depender del warning.

**Archivos:** `kateto/providers/edgetts.py`
