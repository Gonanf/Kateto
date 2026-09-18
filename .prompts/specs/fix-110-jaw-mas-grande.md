# Jaw: el movimiento quedó corto — hay que subirle amplitud y agresividad

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"El movimiento de Jaw es muy poco, debe ser más alto y más agresivo."

## Estado actual (código y medición)
`kateto/plugins/visual_overlay/web/kateto-avatar.js`:
```js
export const JAW_MAX_TRAVEL_PX = 16.0;
export const JAW_MAX_TILT_DEG = 4.5;
export const HEAD_BOB_PX = 1.8;
export const FLAP_HZ = 8;
// factor = pow((rms - 0.015) / 0.985, 0.68)   <- curva de respuesta
// openMovement = factor * JAW_MAX_TRAVEL_PX * flap   (flap = 0.5 + 0.5*sin(2π*8Hz*t))
// sideShake = ±factor * 9.0 px ; tilt = ±factor * JAW_MAX_TILT_DEG
```
Medición de referencia (post bug 112, con `script/qa/measure_jaw.mjs`): **min/max/mean = 0.02 / 13.69 /
4.79 px**, 90/90 positivos, 24 cruces en 1 s, silencio = 0, tilt ±4.5°.
O sea: el tope teórico es 16 px pero el recorrido real promedio es **~4.8 px** — se ve poco y sin
punch. `computeBackendKinematics` (path backend) comparte las mismas constantes: si cambiás el tope,
cambia en los dos y tiene que seguir siendo coherente (ver la convención del encabezado del archivo:
positivo = boca abierta, silencio = 0, sin piso fijo).

## Fix esperado
1. **Subir el recorrido**: `JAW_MAX_TRAVEL_PX` a un valor que dé un máximo medido de **~28-32 px**
   (arrancá por 30 y ajustá con la medición; el máximo medido no es el tope teórico).
2. **Más agresivo, no sólo más grande**:
   - curva de energía más punchy (bajar el exponente de 0.68 hacia ~0.5-0.55) para que la boca responda
     fuerte con poca voz;
   - flap con ataque más marcado (que el pico del flap sea más filoso: p.ej. aplicar una potencia al flap
     o cambiar la forma de onda), cuidando que **siga cruzando el neutro** varias veces por segundo
     (los cruces no pueden bajar de ~20/s);
   - `FLAP_HZ` puede subir a 9-10 si la medición acompaña;
   - shake lateral y tilt proporcionalmente más visibles (tilt hasta ~6-7°, shake ~12 px), siempre
     acotados: el bug histórico fue un tilt de ±40°.
3. **Sin silencio no hay movimiento** (se mantiene): el gate en `rms < 0.015` y el silencio exacto = 0.
4. **Nada de piso fijo** (bug 112): el flap multiplica 0..1, nunca suma un piso.
5. Mantené la coherencia con `computeBackendKinematics` (mismos topes) y actualizá los comentarios con
   los números nuevos.
6. Que no se mueva el personaje entero: sólo la capa del jaw (el shake va en `jawOffsetX`, no en un
   `transform` de la tarjeta).

## Verificación con números (obligatoria, antes/después)
Corré `script/qa/measure_jaw.mjs` y reportá **min/max/mean, cuántos positivos, cruces por segundo,
silencio=0, tilt máximo** para:
- antes (podés citar los de arriba) y después de tu cambio;
- al menos dos niveles de energía (voz baja y voz fuerte), para mostrar que escala;
- y que el silencio sigue dando 0.
Ajustá las constantes hasta caer en: **max ≈ 28-32 px**, mean ≥ 9 px, cruces ≥ 20/s, silencio 0.

## Tests
- `kateto-avatar.test.mjs`: los asserts actuales de jaw quedan desactualizados — actualizalos con los
  valores nuevos y agregá uno de "más energía ⇒ más recorrido" y otro de "silencio ⇒ 0 exacto".
- `test_visual_overlay.py` sigue verde.
- Los tests existentes del overlay/avatar siguen verdes.

## Docs
- Bug nuevo (id siguiente) o actualización del 112: "el recorrido del jaw quedó corto tras la
  corrección de dirección: subir amplitud y agresividad", con la tabla antes/después.

## Verificación final (sin `| tail`)
1. `node kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` (o el runner que use el repo)
2. `.venv/bin/python -m pytest kateto/tests/ -q -k "visual or overlay"`
3. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **536 passed / 3 failed** (preexistentes)
4. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar assets del avatar. Mover el personaje entero. Dejar el jaw sin volver
  a 0 en silencio.
