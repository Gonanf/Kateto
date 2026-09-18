# Jaw: la capa que se mueve tiene que subir (no bajar) y abrir la boca de verdad

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"Además el Jaw se mueve hacia abajo y no hacia arriba y más alto como debería."

## Causa (verificada mirando los assets, no leyendo código)
Las dos capas del avatar son:

- `avatar_jaw.png` — el `.layer-jaw` **que se anima** (`z-index: 1`, detrás): es la parte **de ARRIBA**
  de la cabeza (pelo, frente, cejas, ojos, nariz, boca con dientes). Corte horizontal a la altura de la
  boca. Verificado con visión sobre Jane (498 KB) **y** doktor (650 KB).
- `avatar_head.png` — el `.layer-head` (`z-index: 2`, delante): es la parte **de ABAJO** (labios, mentón,
  barba, cuello, torso). Corte a la altura de la boca.

O sea: **la capa que se mueve es la de arriba**. Con la convención actual
(`jawOffsetY` positivo = `translateY(+)` = hacia abajo, ver `kateto-avatar.js`) la pieza de arriba
**baja** al hablar: se superpone sobre la de abajo y el efecto es que la boca se cierra/hunde en vez de
abrirse. Por eso el usuario lo ve "hacia abajo". Abrir la boca = **esa capa sube** (y aparece la luz
entre las dos piezas, estilo Muppet).

## Fix esperado
1. **Invertir el sentido del recorrido** de la capa que se mueve: al hablar, sube.
   - En el JS: `jawOffsetY` negativo = arriba = boca abierta (hoy positivo va abajo). El signo se aplica
     en un solo lugar por path (`computeJawKinematics` y `computeBackendKinematics`), no repartido.
   - En el backend (`kateto/core/rms.py::map_rms_to_jaw_transform` / `map_rms_to_puppet_transform`): el
     mismo signo, para que los dos paths sigan coincidiendo (hoy comparten los topes).
   - **Actualizá los comentarios de convención** (`SHARED CONVENTION`, bug 112) que hoy dicen
     "positivo = mandíbula baja = boca abierta": eso quedó al revés con estos assets. Dejá escrito qué
     significa cada signo, para no volver a invertirlo por accidente.
2. **Más recorrido hacia arriba** ("más alto"): mantené/ajustá el tope para que la medición dé un
   recorrido **hacia arriba** de ~28-32 px en voz fuerte (el tope teórico es 32). Si hace falta subilo un
   poco, pero que la medición mande.
3. **Revisá el head bob** (`.layer-head`, la pieza de abajo): hoy `headOffsetY = -factor * HEAD_BOB_PX`
   (hacia arriba). Con la nueva geometría, subir la pieza de abajo **cierra** la boca: tiene que ser 0 o
   un pequeño movimiento hacia **abajo** (así ayuda a abrir), y volver a 0 en silencio.
4. **Contenedor**: `:host`/`.container` tienen `overflow: visible`, así que subir la capa no se recorta.
   Verificá que igual no se salga del encuadre con el tope nuevo (si se sale, bajá el tope, no cambies
   el layout).
5. El tilt (`jawRotation`) y el shake lateral siguen existiendo: revisá que con el signo invertido el
   gesto siga leyéndose como boca (no como cabeza torcida) y, si queda raro, invertí también el tilt.
6. Silencio = 0 exacto, sin piso fijo (bug 112). El fallback (`mouth.png`/`top.png`) no se toca.

## Verificación con números (obligatoria, antes/después)
`script/qa/measure_jaw.mjs` tiene que reportar, para voz normal y voz fuerte:
- **valores negativos** con magnitud máxima ~28-32 px (subida) y promedio ≥ 9 px;
- cruces por el neutro ≥ 20/s;
- silencio = 0 exacto;
- la pieza de abajo (head) sin subir cuando habla.
Dejá la tabla antes/después en el resumen y en el bug.

## Tests
- `kateto-avatar.test.mjs`: asserts invertidos (hablando ⇒ `jawOffsetY < 0`, magnitud en rango,
  silencio ⇒ 0; y que "más energía ⇒ más subida").
- `kateto/tests/` para el path del backend (`map_rms_to_jaw_transform` con rms alto ⇒ negativo).
- Los tests de overlay existentes siguen verdes.

## Docs
- Bug nuevo (id siguiente) "la capa animada es la de arriba: al hablar tiene que subir, no bajar", con
  la evidencia de los assets (visión sobre `avatar_jaw.png` de jane y doktor) y la tabla de medición.
- `known-issues.md` + `plugins/visual_overlay.md` (o el doc del overlay que exista) con la convención de
  signos.

## Verificación final (sin `| tail`)
1. `node --test kateto/plugins/visual_overlay/web/kateto-avatar.test.mjs` (reportá tests/pass/fail)
2. `.venv/bin/python -m pytest kateto/tests/ -q -k "visual or overlay or rms"`
3. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **557 passed / 3 failed** (preexistentes)
4. `git diff --stat`

## Prohibido
- Commitear. Subagentes/task. Tocar los assets del avatar (son del usuario). Cambiar la convención en un
  solo path y no en el otro. Dejar la boca cerrada en silencio distinto de 0.
