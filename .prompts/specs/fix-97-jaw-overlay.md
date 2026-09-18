# Overlay: la mandíbula sólo se mueve hacia arriba (no hay ciclo abre/cierra)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma reportado (usuario, en vivo)
"La animación de jaw en el visual overlay sólo mueve para arriba, sin realmente hacer el movimiento de
arriba y abajo para simular una boca que se mueve."

## Causa candidata — verificá vos antes de tocar nada
`kateto/plugins/visual_overlay/web/kateto-avatar.js` → `computeJawKinematics(rms, nowMs)` (líneas ~15-38):

```js
const flap = 0.5 + 0.5 * Math.sin((t / 1000) * 2 * Math.PI * 8);
const upMovement = -Number(((6.0 + 40.0 * flap) * (0.5 + 0.5 * factor)).toFixed(2));
...
return { jawOffsetX: sideShake, jawOffsetY: upMovement, jawRotation: tilt };
```

`6.0 + 40.0 * flap` es **siempre positivo** (flap ∈ [0,1]) y el signo va pegado afuera → `jawOffsetY`
**nunca es ≥ 0**: es un desplazamiento permanente hacia arriba con wobble (entre ~-3 y ~-46 px), nunca
vuelve a la posición neutra ni cruza el cero. Eso se lee exactamente como "sólo se mueve para arriba".
Además el comentario del archivo dice que este path es el *primary* tanto para TTS sintético (`pulseWord`)
como para audio vivo (`setRms`).

Y hay **segundo path** con la convención al revés: `computeBackendKinematics(rms)` y
`map_rms_to_puppet_transform` (`kateto/core/rms.py:78`) devuelven `jawOffsetY = +factor * 16.0`
(positivo, 0..16) con `headOffsetY = -factor * 1.8`. O sea: backend = positivo, front-end local =
siempre negativo. Mientras convivan, `setJawTransform` (backend) y `setRms` (local) van a saltar entre
dos convenciones opuestas.

**No asumas**: medí primero (paso 1) y recién después cambiá. Si la medición muestra algo distinto a lo
de arriba, seguí lo que muestre la medición y documentá la causa real.

## Paso 1 — reproducir y medir (obligatorio, antes del fix)
Con un navegador headless (Playwright/Chromium vía Bun o Node; hay `node`, `bun` y `deno` en la máquina;
hay skills de QA con browser en este repo) montá `kateto/plugins/visual_overlay/web/index.html` (o el
componente `<kateto-avatar>` con `kateto-avatar.js`) y alimentá una señal sintética:
1. silencio (rms 0) ~0.3 s,
2. habla (rms ~0.5 oscilante, o una secuencia de rms 0.2/0.5/0.8) ~1.5 s,
3. silencio otra vez ~0.4 s.

Muestreá el bounding box (o el `transform` computado) de la capa de la mandíbula a ~60 Hz y reportá:
- `min`, `max`, `mean` de `jawOffsetY` (y el signo dominante),
- si **vuelve a la posición neutra** (0) durante la señal y al final,
- **cuántas veces cruza el neutro** (oscilaciones completas) durante el habla: hoy se espera ~0,
- si hay **salto** al alternar entre el path del backend y el local.

Guardá esa medición como evidencia (números en el reporte + el script en `script/qa/` si lo hacés ahí).

## Paso 2 — el fix
- Una sola convención para los dos paths, y que el neutro sea **boca cerrada** (transform 0). El
  movimiento debe ser un **ciclo real**: abre (se aleja del neutro) y cierra (vuelve a 0), varias veces
  por segundo mientras hay voz; con silencio, la mandíbula queda en el neutro.
- `computeJawKinematics`: la amplitud tiene que escalar con la energía de la voz y **irse a 0 con el
  silencio** (hoy hay un piso constante de 6 px que la deja arriba para siempre). Sin piso constante:
  `amplitud = f(factor)` con `factor → 0` en silencio. El flap debe multiplicar la amplitud, no sumarse
  a un offset fijo.
- Respetá el rango útil del backend (≤16 px de travel) para que las dos rutas se vean igual; si el arte
  necesita más recorrido, dejalo configurable en un solo lugar, no dupliques constantes mágicas.
- El jitter lateral (`jawOffsetX`) y el tilt son secundarios: si el tilt actual es absurdo (±40°),
  acotalo, pero **no cambies** el look general más allá de lo necesario para arreglar el arriba/abajo.
- No debe quedar la mandíbula "pegada arriba" al terminar de hablar (verificá el cierre también al final
  del turno: el plugin resetea la EMA en `visual_overlay_plugin.py` ~línea 117 — comprobá que eso llegue
  al overlay).

## Paso 3 — tests (obligatorios, tienen que correr con `uv run pytest`)
- Test JS de `computeJawKinematics` (archivo nuevo, p.ej. `kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs`)
  que recorra ~1 s de `nowMs` con rms de habla y verifique: el mínimo es ≈ 0 (o cruza 0), el máximo es
  > 0, y hay **≥ 4 cruces por cero** (ciclo abre/cierra real). Con rms 0 → exactamente 0.
- Un test de pytest que ejecute ese archivo (con `bun test` o `node --test`, `skip` si el runtime no
  está) para que `uv run pytest` lo cubra de verdad, más el test de la convención compartida entre
  `computeBackendKinematics` y el mapeo Python (`map_rms_to_puppet_transform`) — mismo signo, mismo signo
  de `headOffsetY`.
- Los tests existentes de `kateto/tests/test_visual_overlay.py` no se rompen; si alguno afirmaba la
  convención vieja, actualizalo y explicá por qué en el docstring.

## Docs
- Bug nuevo (id siguiente) "jaw del overlay sólo se mueve hacia arriba (no hay ciclo abre/cierra)" con la
  medición antes/después.
- `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. la medición del paso 1 (antes) y la misma medición después del fix, con los números al lado
2. `.venv/bin/python -m pytest kateto/tests/test_visual_overlay.py -q`
3. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline del worktree: **473 passed / 3 failed** preexistentes
4. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Inventar la medición del browser (si no podés correr un navegador headless,
  decilo y hacé la medición sobre el JS con un DOM mínimo, pero no inventes números).
- Tocar la config del usuario.
