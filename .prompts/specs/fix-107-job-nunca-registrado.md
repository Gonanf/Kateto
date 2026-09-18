# Visión periódica: el job nunca se registra (se pide el schedule durante `enable()`, antes de que el scheduler escuche)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"El vídeo rag no se está ejecutando de vuelta, lo había configurado cada 30 segundos y antes funcionaba
pero ahora ya no."

La config está bien: `jane.vision_periodic = true` + `jane.vision_interval = "30s"` en el config
principal, y los `config.toml` por voz ya no tienen esas claves (nada las pisa). El runtime tiene
`static_vision` y `executor_scheduler` enabled.

## Causa (leída en el código, con el orden de arranque medido)
1. `kateto/run_mode.py:139-141`: los plugins se habilitan **en serie**, en el orden de `self._plugins`:
   `for plugin in self._plugins: await self._manager.enable_plugin(plugin)`.
2. `kateto/core/manager.py::enable_plugin` (74-92): llama `plugin.enable()` **antes** de registrar al
   plugin en `self._plugins` y antes de suscribir sus handlers.
3. `kateto/plugins/executor/static_vision_plugin.py::enable()` (232-256) llama `_schedule_periodic()`,
   que **emite `schedule_request`** (#271-283) y loguea
   `[vision] scheduled {job_id} every {interval} for {voice}` **incondicionalmente**, sin ack.
4. Si `static_vision` se habilita antes que `executor_scheduler`, ese `schedule_request` no tiene ningún
   suscriptor todavía: `manager.emit` lo despacha a cero receptores (sólo `log.debug("dispatch ... to []")`)
   y **se pierde en silencio**. El scheduler nunca registra el job, y el plugin nunca reintenta.
5. El orden real medido en el runtime del usuario (`GET /plugins`) es el orden de habilitación, y ahí
   `static_vision` es el **#16** y `executor_scheduler` el **#25** ⇒ la petición se emite antes de que el
   scheduler escuche. Es una carrera de arranque: según el orden, el job se registra o no (de ahí el
   "antes funcionaba y ahora no").

Evidencia de que la cadena en sí funciona: un `vision_describe_request` inyectado a mano
(`POST /events/send`) sí llega a `static_vision` (el evento `vision_describe_request` figura con receiver
`static_vision` en `GET /events`) y dispara el describe. Lo que falta es **el job**.

## Fix esperado
1. **El ack manda.** `executor_scheduler` ya emite `schedule_result` (`ScheduleResultData(job_id,
   next_run, error)`, scheduler.py:149-153). Que `static_vision` lo escuche:
   - `_periodic_jobs.append(job_id)` **sólo cuando llega el ack** (hoy se agrega al emitir: si el emit se
     pierde, no se reintenta nunca).
   - La línea `[vision] scheduled ...` se mueve al ack; en el emit no se afirma nada.
   - Si llega `error`, loguear el motivo (WARNING) y no reintentar en loop infinito.
2. **Reintento acotado hasta lograr el registro.** Guardá las peticiones pendientes (voz → interval) y
   reintentá con backoff corto (p.ej. a los 2s, 5s, 10s, 20s, 30s, luego cada 30s hasta ~2 minutos).
   Se corta en cuanto llega el ack. Si se agotan los intentos: **un** WARNING claro del tipo
   `[vision] vision-describe-jane NOT registered after 6 attempts (is executor_scheduler enabled?)`, con
   el motivo (`_periodic_skipped` si la voz no existe todavía) y sin spam.
3. **Reevaluá las voces desconocidas en cada reintento**: `_schedule_periodic` hace
   `known = {... capabilities includes "voice"}` y hoy, en `enable()`, ese conjunto puede estar vacío o
   incompleto; con el reintento tiene que resolverse cuando las voces ya están registradas.
4. **Sin duplicados**: un solo job por voz (mismo `job_id`), y cancelar los pendientes en `disable()`.
5. Opcional pero valioso: documentá el trap general en `docs/` (un evento emitido desde `enable()` no
   tiene receptores: el manager suscribe **después** de `enable()`), y considerá un aviso en
   `Plugin.enable`/`manager.emit` cuando un `schedule_request` queda sin receptores (sin romper eventos
   legítimamente sin consumidores).

## Tests (obligatorios)
- **El caso exacto**: habilitar `static_vision` (con `opted_in=(("jane","30s"),)`) **antes** que el
  scheduler ⇒ el emit se pierde, no hay ack, se loguea el WARNING de no-registrado; después de habilitar
  el scheduler, el reintento registra el job, llega el ack, se loguea `registered` y `scheduler._jobs`
  contiene `vision-describe-jane`.
- Con el scheduler ya habilitado: un solo emit, un solo ack, sin duplicados ni reintentos de más.
- `disable()` cancela el job y limpia los pendientes.
- Un ack con `error` no genera loop de reintentos y queda logueado.
- Los tests existentes de `test_vision_lifecycle.py` siguen verdes (ojo: varios asumen el log inmediato).

## Docs
- Bug nuevo (id siguiente): "el job de visión periódica no se registra cuando el plugin se habilita antes
  que el scheduler: la petición se emite sin receptores y se pierde en silencio".
- `known-issues.md` + `plugins/vision.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or scheduler"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **510 passed / 3 failed**
   (preexistentes: `test_audio_capture`, 2× `test_voice_history`)
3. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Inventar que "ya se registra": el test tiene que
  probar el orden de arranque real (vision antes que scheduler).
