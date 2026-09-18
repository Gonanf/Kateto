---
id: 113
title: "Segfault en libasound al interrumpir: close del stream con un write en vuelo"
severity: Crítica
status: resolved
component: kateto/plugins/audio_output/player.py
resolved: 2026-09-18
---

## 113. Segfault en libasound al interrumpir: close del stream con un write en vuelo

**Severidad:** Crítica
**Componente:** `kateto/plugins/audio_output/player.py`

### Descripción

Con TTS a mitad de reproducción (`played ... audio_ms=5640`), un barge-in por
voz mató el proceso. El kernel logueó:

```text
sep 18 13:43:28 chaman kernel: kateto[305244]: segfault at 70 ip 00007f6c6818da22
  sp 00007f6bc237d358 error 4 in libasound.so.2.0.0[31a22,7f6c6817e000+a0000] likely on CPU 7
```

y el log de Kateto corta exactamente ahí (13:43:28.745-747):

```text
[mic] Speech detected, recording...
[edgetts] interrupt voice=jane
[player] interrupt reason=voice_activity dept=fun
[player] stream close abort=False
turn_gate: dropped 0 queued turn(s) on user interrupt
```

coredumpctl registra el SIGSEGV de `python3.12` del 2026-09-18 13:43:51. El dump
lo pudo leer el usuario del entorno y **su backtrace confirma la causa**: el
thread que murió es el de la escritura (TID 305244, el mismo `kateto[305244]`
del kernel log), dentro del camino de poll de ALSA de PortAudio:

```text
Stack trace of thread 305244:
#0  libasound.so.2 + 0x31a22
#1  snd_pcm_poll_descriptors_revents (libasound.so.2 + 0x7dba4)
#2  libportaudio.so.2 + 0xd514
#3  libportaudio.so.2 + 0x13b2f
#4  libportaudio.so.2 + 0x14c2b
#5  ffi_call_unix64 (_cffi_backend.cpython-312-x86_64-linux-gnu.so)
#9  _PyEval_EvalFrameDefault (python3.12)
#10 method_vectorcall
#12 context_run
```

O sea: no fue `close()` reventando solo, fue el **`write()` en vuelo** el que
pisó memoria que otro thread ya había liberado. Hay SIGSEGV/SIGABRT de
`python3.12` en coredumpctl desde el 2026-08-28: la familia ya existía (bugs 63,
81, 84, 86). Lo que cambió es que el interrupt ahora sí dispara en cada
barge-in, así que este path pasó de casi nunca correr a correr todo el tiempo.

### Impacto

Muerte del proceso en pleno barge-in: el usuario interrumpe y Kateto desaparece.

### Causa

Carrera entre el hilo de escritura y el cierre, en `AudioOutputPlayer`:

1. El mixer escribe con `_ = await to_thread.run_sync(stream.write, pcm)`
   (`player.py`, `_run_mixer`). `to_thread.run_sync` **no es cancelable**: al
   cancelar la task, el `await` se libera pero el hilo worker sigue dentro del
   `write()` de PortAudio hasta terminar el bloque.
2. `on_interrupt` hacía `_close_stream()` **y recién después** cancelaba
   `_mixer_task`. `_close_stream` llama `stream.stop()` + `stream.close()`.
3. Resultado: PortAudio desarma el stream ALSA (área mmap) mientras el otro
   hilo sigue escribiendo. El fault leyendo offset `0x70` en `libasound` es el
   camino clásico de `snd_pcm_mmap_*` sobre un `pcm` ya liberado.

Por eso `to_thread` + `cancel` no alcanza: cancelar solo calla al que espera,
no al que escribe. Hacía falta exclusión mutua real entre el write y el
teardown, más cancelar el mixer antes de cerrar para que no arranque otro
write entre medio.

### Relación con decisiones previas (siguen valiendo)

- **63/81**: el stream se abre/cierra por turnos (no persistente) para no
  putrir buffers ALSA entre turnos. Se mantiene.
- **84**: `write()` reactiva el stream si está detenido. Se mantiene.
- **86**: nunca `abort()` — doble free en el camino mmap de PortAudio. Se
  mantiene (el `ponytail:` sigue en `_close_stream`); el fix usa `stop()` +
  `close()` bajo lock.
- **88**: el write que falla cierra y reabre en la iteración siguiente. Se
  mantiene y queda cubierto por test (no se rompió).

### Solución aplicada

1. `SoundDeviceOutputStream` lleva un `threading.RLock` propio (no un
   `asyncio.Lock`: el write corre en un worker thread de `to_thread`). `write`,
   `start`, `stop`, `close` lo toman; el nuevo `shutdown()` hace `stop()` +
   `close()` bajo **una** adquisición para que ningún write se cuele entre
   medio. Los llamadores internos del mixer (idle timeout, write fallido,
   reopen) corren en la propia task sin write en vuelo, así que nunca bloquean
   ahí; el RLock cubre la re-entrada del path de error de `write()`.
2. `on_interrupt` y `disable` ahora cancelan la task del mixer con el helper
   `_cancel_mixer_task()` (cancela y espera su muerte con timeout de 2 s)
   **antes** de `_close_stream()`. Cancelar evita writes nuevos; el lock del
   close espera al write abandonado en vuelo.
3. Trade-off de inmediatez: el barge-in espera como máximo **un bloque en
   vuelo** (decenas de ms con `blocksize=1024`) antes de `stop()`. No se cambió
   por un cierre diferido: el usuario oye como máximo una cola de ~40 ms y
   después silencio. Si el backend cuelga un write para siempre, el close
   espera con él (mismo compromiso que cualquier teardown serializado).

**Archivos:** `kateto/plugins/audio_output/player.py`,
`kateto/tests/test_player_stream_close_race.py`
