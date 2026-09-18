# Segfault en libasound al interrumpir: cerrar el stream mientras hay un write en vuelo

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Evidencia dura (runtime real del usuario, hoy 2026-09-18)
Kernel log:
```
sep 18 13:43:28 chaman kernel: kateto[305244]: segfault at 70 ip 00007f6c6818da22
  sp 00007f6bc237d358 error 4 in libasound.so.2.0.0[31a22,7f6c6817e000+a0000] likely on CPU 7
  Code: ... 4c 8b 8b 4c 8b 40 20 <4d> 8b 40 70 4d 85 c0 ...
```
Y el log de Kateto corta exactamente ahí (13:43:28.745-747), con el TTS a mitad de reproducción
(`played ... audio_ms=5640` a las 13:43:28.655):
```
[mic] Speech detected, recording...                     <- 13:43:28.745
[edgetts] interrupt voice=jane
[player] interrupt reason=voice_activity dept=fun
[player] stream close abort=False                        <- _close_stream()
turn_gate: dropped 0 queued turn(s) on user interrupt
```
Coredump: `Fri 2026-09-18 13:43:51 SIGSEGV, uid 1001, python3.12` (el dump es de él, no lo puedo leer).
Histórico: hay SIGSEGV/SIGABRT de `python3.12` en coredumpctl desde el 2026-08-28, así que **la familia
ya existía** (bugs 63, 81, 84, 86) — lo que cambió hoy es que el interrupt ahora **sí** dispara en cada
barge-in, así que este path pasó de casi nunca correr a correr todo el tiempo.

## Hipótesis a confirmar (marcá qué confirmás y con qué)
El mixer escribe desde un hilo de trabajo:
`kateto/plugins/audio_output/player.py:312` → `_ = await to_thread.run_sync(stream.write, pcm)`.
`to_thread.run_sync` **no es cancelable**: al cancelar la task, el hilo sigue hasta terminar el write.
Y `on_interrupt` (línea ~434) hace: `_close_stream()` → **y recién después** cancela `_mixer_task`.
`_close_stream` (línea ~485) llama `stream.stop()` + `stream.close()`.
→ Si hay un `write()` en vuelo, PortAudio desarma el stream ALSA (mmap) mientras el otro hilo escribe:
el fault en `libasound` leyendo offset `0x70` es clásico de ese camino (`snd_pcm_mmap_*`).

Leé primero `docs/src/content/docs/bugs/{63,81,84,86}-*.md`: hay historia de abort()/xrun/reactivación.
No repitas decisiones ya documentadas sin explicar por qué siguen valiendo.

## Fix esperado
1. **Orden y serialización**: nunca cerrar (ni `stop()`) el stream con un `write()` en vuelo.
   Poné el `write` y el cierre bajo la misma exclusión mutua real (un `threading.Lock`/`RLock` tomado
   *dentro* del hilo que escribe y en `_close_stream`), o esperá explícitamente a que el write en vuelo
   termine antes de tocar el stream. `to_thread.run_sync` + cancel **no** alcanza: documentalo.
2. **Cancelar el mixer antes que el stream** (y esperar a que la task muera, con timeout) para que no
   arranque otro write entre medio. Si el orden actual (cerrar → cancelar) es intencional, explicá por qué.
3. Cuidá los otros llamadores de `_close_stream`: `_run_mixer` (idle timeout ~297 y write fallido ~337)
   corren dentro de la propia task del mixer — verificá que sigan seguros con la serialización nueva
   (no querés un deadlock: si el lock se toma en el mismo hilo, usá reentrante o no lo tomes dos veces).
4. La interrupción tiene que seguir siendo **inmediata** (el usuario quiere que se calle ya): no cambies
   el barge-in por un "cerrá en 1.5 s". Si algo se pierde en el camino, decilo y explicá el trade-off.
5. Nada de `abort()` (bug 86: doble free en el camino mmap de PortAudio) — respetá el `ponytail:` existente.

## Tests (obligatorios, con el patrón de fakes del repo)
- Fake de stream que registre el orden de operaciones y **falle el test** si `stop()`/`close()` ocurre
  mientras un `write()` está en vuelo (p.ej. write que duerme 50 ms y marca un flag "escribiendo").
  Tiene que fallar ANTES del fix y pasar después.
- Test de que `on_interrupt` no retorna habiendo cerrado con un write in-flight, y que **no** se escribe
  nada después del close.
- Test de que el write que falla sigue cerrando y reabriendo como hoy (no lo rompas).
- Los tests de audio existentes siguen verdes.

## Docs
- Bug nuevo (id siguiente, verificá el máximo en `docs/src/content/docs/bugs/`) con la evidencia del kernel,
  la conexión con 63/81/84/86 y la explicación de por qué `to_thread` + cancel no alcanza.
- `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "audio or player or output"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **475 passed / 3 failed** preexistentes
3. `git diff --stat`

## Datos que puedo traer si te sirven
Si hay backtrace del coredump, va a estar en `/var/tmp/kateto-fix/coredump-kateto.txt` (lo corre el usuario).
Si existe, usalo para confirmar el frame; si no está, no lo inventes.

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Inventar reproducción: si no podés reproducir
  el segfault (hace falta hardware), el test del orden de operaciones es la evidencia, y decilo así.
