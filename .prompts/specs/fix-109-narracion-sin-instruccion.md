# La voz recibe el caption de visión como dato pelado y pregunta "¿qué querés que haga con esto?" (encima en inglés)

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Síntoma (usuario, textual)
"El agente no sabe que hacer con esta información que tiene del vídeo rag, por lo que dice (en inglés
encima) 'What do you want me to do with this information?'."

## Causa (leída en el código)
1. La narración ambiental emite el caption como **dato pelado**, sin ninguna instrucción
   (`kateto/plugins/executor/static_vision_plugin.py`, `on_vision_describe_request`):
   ```python
   GenerateData(prompt=f"[look-at {source} {span:.0f}s{frames_note}]: {fused}")
   ```
   Eso llega al modelo como mensaje de usuario con un blob `[look-at …]: <caption>` y **nada que le diga
   qué es ni qué hacer con eso** ⇒ contesta "What do you want me to do with this information?".
2. La skill `look-at` (`config/defaults/skills/look-at/SKILL.md`) explica cómo **pedir** una mirada
   (tool `send_event`) y que el resultado "lands in your memory as `[look-at <source> <span>s]: ...` —
   answer from it", pero eso es guía para el caso en que **el usuario pide** que mire. En la narración
   ambiental nadie pidió nada: el modelo no tiene disparador conversacional y no sabe que la mirada es
   **suya**.
3. `VoiceAgent.on_vision_describe_result` es un **no-op** (`voices/base.py:653`): la descripción sólo
   queda en memoria vía `_remember_event`. O sea que tampoco hay un punto que arme el turno con
   instrucción; depende de que el modelo adivine.
4. El idioma: el prompt estable ya trae la regla
   (`voices/context.py:80-84`: "Always respond in the project's configured language: {response_language}.
   This instruction overrides the language of the user input."), pero con un blob sin instrucción un
   modelo chico (el de voz es `nemotron-3.5-lightning-30b-a3b`) se va al default en inglés. La
   instrucción del turno tiene que ser explícita y en el idioma configurado, sin depender de la regla
   general.

## Fix esperado
1. **El turno de visión tiene que ser una instrucción, no un dato.** Cuando el prompt que se manda al
   modelo viene de una mirada (`[look-at …]`), envolverlo con una instrucción clara, en el idioma
   configurado y en personaje. Contenido mínimo de la instrucción:
   - que la mirada es **propia de la voz** (vos miraste, no el usuario);
   - que comente lo que ve en 1-2 frases, en personaje;
   - **prohibido** pedir instrucciones o preguntar qué hacer con la información;
   - que no invente lo que no está en el caption.
   Elegí dónde vive: (a) el plugin arma la instrucción completa (necesita el idioma de la voz), o
   (b) la voz reconoce el prefijo `[look-at …]` al construir el turno y lo envuelve con su idioma y
   persona. **Recomendado (b)**: la voz es la que sabe su idioma/persona, y así vale para los dos casos
   (narración ambiental y resultado de un look-at pedido). Explicá en el diff por qué elegiste una.
2. **Idioma explícito en el turno**, tomado de la config de la voz (`response_language`), no hardcodeado
   a español; si no hay idioma configurado, caé al texto en el idioma del proyecto (el que ya usa
   `context.py`).
3. **Mismo tratamiento para el resultado pedido**: el texto que ve el modelo cuando él mismo pidió la
   mirada también tiene que decir que es su propia observación y que la use para responder — hoy es un
   volcado del caption sin marco.
4. **La skill `look-at`** tiene que reflejar esto: agregar en `SKILL.md` (defaults) que cuando llega un
   bloque `[look-at …]` (ambiental o pedido) la respuesta es **narrar/comentar en personaje**, nunca
   preguntar qué hacer. Ojo con `ensure_shared_skill`: los cambios en la skill bundled se refrescan con
   backup, así que el usuario la recibe al reiniciar.
5. Nada de esto puede cambiar el prompt estable congelado: la instrucción del turno va en la parte
   volátil (historial/turno), no en el prefijo cacheable.

## Tests (obligatorios)
- Un `generate` con prompt `[look-at screen 5s]: <caption>` ⇒ el mensaje de usuario que se arma contiene
  la instrucción (mirada propia + no pedir instrucciones) y el idioma configurado, y el caption intacto.
- Un `generate` normal (sin prefijo `[look-at`) **no** se envuelve (no rompas la charla normal).
- El idioma sale de la config de la voz: con `response_language = "en"` la instrucción va en inglés
  (que no quede español hardcodeado).
- El resultado del look-at pedido (camino de tool/event) también llega con el marco.
- Los tests existentes de visión/voces siguen verdes.

## Docs
- Bug nuevo (id siguiente) "la voz recibe el caption como dato pelado y pregunta qué hacer con él".
- `known-issues.md` + `plugins/vision.md` + `references` de la skill si aplica.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or voice or prompt"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **536 passed / 3 failed** (preexistentes:
   `test_audio_capture`, 2× `test_voice_history`)
3. `git diff --stat`
4. Si podés, mostrá en el resumen **el prompt final** que recibe el modelo para una narración de 5s
   (literal), antes/después.

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Elegir modelos. Reescribir el caption.
