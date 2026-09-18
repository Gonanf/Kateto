# La narración cae siempre en las mismas fórmulas ("Me parece interesante que…", "el usuario está aprendiendo…")

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## REGLA 0 (leela primero)
**Prohibido explorar.** Abrí sólo lo que está acá y andá directo al patch. Los tests a escribir son los
de la sección **Tests**.

Anclas:
- `kateto/voices/base.py` — `frame_look_at_turn(block, response_language)` (~línea 110, con las dos
  ramas de idioma); sus dos llamadas (~1473 y ~1497); `VoiceAgent.__init__` (~502-514, donde viven
  `_followup_pending`, `_interrupted`); el punto donde el turno termina y hay texto final
  (`FinalMessage`, `_stream_response`).
- `kateto/plugins/executor/static_vision_plugin.py` — el gate de repetición de caption (fix-111,
  `_caption_ratio` ~1021) como **patrón a espejar** para similitud de texto, y `_last_narrated` (~383).
- Tests existentes del marco: `kateto/tests/test_vision_repeat_opinion.py`,
  `kateto/tests/test_vision_turn_framing.py`, `kateto/tests/test_vision_ocr_detect.py`.

## Pedido del usuario (textual)
"cuando el agente habla sobre lo que se ve, siempre dice cosas por el estilo de 'Me parece interesante
que…', '..el usuario está aprendiendo…'. Esto no se resuelve con un blacklist de palabras, hay que ver
una mejor solución."

**Restricción dura: nada de listas negras de palabras.** Prohibir "interesante" sólo mueve la fórmula de
lugar. La solución tiene que ser estructural.

## Por qué pasa (causa, no síntoma)
1. El marco actual **pide una reseña** ("opiná… qué te parece, qué te llama la atención") — y una reseña
   arranca con fórmulas de reseñador ("me parece interesante que…"). Es el registro que la propia
   instrucción induce.
2. El material es un caption **neutral y en tercera persona** ("el usuario está…"), así que el modelo
   comenta *sobre el usuario* en vez de **hablarle al usuario**. De ahí "el usuario está aprendiendo".
3. No hay ninguna restricción de **forma** ni memoria de lo que ya dijo: con el mismo pedido y material
   parecido, converge siempre al mismo molde. Un modelo chico, todavía más.

## Fix esperado (estructural)

### 1. El marco pasa de "reseñar" a "reaccionar en voz alta"
Reescribí `frame_look_at_turn` (las dos ramas) para que pida un **comentario de alguien que está al lado
mirando la pantalla**, no una opinión de reseñador:
- **Una sola línea corta** (≤ ~18 palabras). Nada de dos frases: el largo es lo que da lugar al relleno.
- **Le habla al usuario de vos** ("che, mirá…", "eso te va a morder"). El usuario **no** se nombra en
  tercera persona, y **no** se comenta su actividad ("está aprendiendo", "está trabajando"): se comenta
  el **contenido** (lo que dice el OCR, lo que se ve). Esto es una regla de quién habla y a quién, no
  una lista de palabras.
- Tiene que sonar a la **persona** (seco, irónico, con opinión concreta y algo discutible), no a un
  crítico amable.
- Se mantiene: prohibido pedir instrucciones ("¿qué querés que haga?") y prohibido inventar lo que no
  está en ninguna sección del material.

### 2. Variedad por construcción: un ángulo distinto por narración
- Definí un pool de ángulos (cortos, para meter en el prompt): **queja** (qué te chirría), **pregunta**
  (una pregunta concreta y punzante sobre el contenido), **predicción** (qué va a salir mal o qué
  sigue), **chiste seco**, **consejo** (qué harías distinto), **dato** (algo concreto que salta a la
  vista en el OCR).
- Cada narración recibe **un** ángulo, sorteado con un rng **inyectable** (tests deterministas), **sin
  repetir el de la narración anterior**. El marco lo dice explícito: "esta vez: <ángulo>".
- Esto es lo que rompe el molde: cambia la **forma** de la respuesta por construcción, no por prohibir
  palabras.

### 3. Memoria de lo dicho (anti-repetición de contenido, no de vocabulario)
- `VoiceAgent` guarda un `deque(maxlen=5)` con **sus últimas narraciones** (el texto final del turno
  cuando el origen es la narración de visión).
- El marco las incluye como "ya dijiste esto — no repitas ni el ángulo ni la forma de arrancar".
- **Backstop numérico**: si la narración nueva se parece ≥ 0.85 (ratio tipo `_caption_ratio`, el mismo
  criterio de fix-111) a cualquiera de las últimas 3, **no se habla**: se loguea y se descarta (el
  ciclo de narración sigue y vuelve a intentar). Mismo espíritu que el gate de caption repetido.
- El deque se limpia al cambiar de idioma/`response_language` no hace falta: es texto, se compara igual.

### 4. Nada de esto toca la estabilidad
- El marco sigue viviendo en el turno volátil (nunca en el prompt estable congelado) — no rompas el
  prefijo cacheable ni la latencia.
- No toques la persona/SOUL ni el pipeline de skills.

## Tests (obligatorios, estructurales)
- El marco (ambos idiomas) contiene el ángulo sorteado y la consigna de **una línea**, dirigida al
  usuario en segunda persona; y **no** contiene el pedido viejo de reseña.
- Con rng sembrado: 6 narraciones seguidas ⇒ **ningún ángulo repetido consecutivo** y al menos 4
  ángulos distintos en total.
- El marco incluye las últimas narraciones cuando el deque no está vacío (y no las incluye si está
  vacío).
- Backstop: una narración con ≥0.85 de similitud contra una reciente ⇒ se descarta y queda log (sin
  `generate`/sin audio).
- Los tests existentes del marco (`test_vision_repeat_opinion.py`, `test_vision_turn_framing.py`,
  `test_vision_ocr_detect.py`) siguen verdes; si alguno asertaba el texto viejo del marco, actualizalo
  **sin debilitarlo** (el aserto tiene que seguir probando lo mismo: marco presente, idioma correcto,
  no pedir instrucciones).

## Verificación (sin `| tail`, reportá conteos)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or framing or prompt or opinion"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline actual: **575 passed / 3 failed**
   (preexistentes)
3. `git diff --stat`

## Docs
Bug nuevo (id siguiente al más alto existente: hay 127, usá **128**) con la causa (marco de reseña +
caption en tercera persona + sin restricción de forma) y la solución, + `known-issues.md`.

## Prohibido
- Listas negras de palabras o filtros de vocabulario.
- Commitear. Subagentes. Mover el marco al prompt estable. Tocar la persona/SOUL.
- Narrar dos veces lo mismo seguido.
