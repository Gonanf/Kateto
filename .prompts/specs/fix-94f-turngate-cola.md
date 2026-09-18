# TurnGate: los turnos encolados no se descartan cuando el usuario interrumpe

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`
(ya incluye los fixes del listener de esta sesión). Seguí ahí. **NO commitees**: dejá el diff visible.

Reporte del usuario, textual: *"Si le hablé, y se calló, solo que se acumuló mensajes y me habló después."*
→ El barge-in **sí** funciona (corta la generación en vuelo y purga las colas del pipeline), pero los turnos
que quedaron **encolados** se contestan después, uno atrás del otro.

## Causa (verificada leyendo el código)
`TurnGate.decide()` devuelve `Decision.QUEUE` cuando `self._active is not None`; `VoiceAgent` entonces
encola el turno en `TurnGate._pending` (`gate.enqueue(...)`) y `_drain()` lo re-emite cuando la voz queda
idle (`on_voice_idle` / `on_voice_status(IDLE)` / `on_audio_output_status` sin PLAYING). `on_interrupt()`
limpia `_active`/`_active_prompt` y pone `_steering = True`, pero **no toca `_pending`**.
Secuencia del síntoma: el usuario interrumpe → la voz se calla → los fragmentos siguientes del usuario
generan más `generate` → el primero ejecuta y los demás se encolan → cuando la voz queda idle, `_drain()`
los emite de a uno → "me habló después" con los mensajes acumulados.

## Fix
1. `TurnGate.on_interrupt`: si el interrupt viene del **usuario** (reason en `{"voice_activity", "user_turn"}`),
   descartá la cola: `dropped = len(self._pending)`; `self._pending.clear()`; y logueá
   `turn_gate: dropped N queued turn(s) on user interrupt`. Los follow-ups entre voces (otro origen/dept)
   mantienen el comportamiento actual: la cola sobrevive.
2. Diagnóstico de cola: al encolar, loguear `turn_gate: queued <event>(<target>) pending=<n>` (el log de
   `draining` ya existe). Así el próximo log muestra si se acumula.
3. No cambies la firma de `enqueue`/`release`/`decide` ni el contrato de eventos.

## Tests (obligatorios)
- Cola con 2 turnos pendientes + interrupt de usuario → `_pending` vacío y **ningún** drenado después.
- Interrupt de otro origen (no usuario) → la cola sobrevive y drena como hoy (regresión del follow-up).
- Después del flush, un `generate` nuevo del usuario **ejecuta** (no queda bloqueado por `_steering`).
- No debilites ni borres los tests existentes de `test_turn_gate.py`.

## Docs
- Bug nuevo con el **siguiente id libre** (verificá el máximo en `docs/src/content/docs/bugs/`):
  "turnos encolados no se descartan tras un barge-in del usuario", severidad Alta, componente
  `kateto/plugins/system/turn_gate.py`.
- `FIX-94.md`: sección nueva con esta causa, el fix y el log.
- `known-issues.md`: el bug nuevo en la tabla que corresponda.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/test_turn_gate.py kateto/tests/test_audio_turn_flush.py kateto/tests/test_audio_barge_in.py kateto/tests/test_audio_turn_chain.py -q`
2. `.venv/bin/python -m pytest kateto/tests/ -q` (reportá el total real)
3. `git diff --stat`

## Prohibido
- Tocar la config del usuario, `capture.py`, `silero.py`, contratos de eventos existentes.
- Subagentes/task. Commitear. Inventar verificación.
