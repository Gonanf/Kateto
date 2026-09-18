# Narración de visión: que opine (no que describa literal) y que se calle si la pantalla es la misma

Worktree: `~/proyectos/OpenaiBuildWeek/kateto-fix-listener-bargein`, rama `fix/listener-turno-bargein`.
**NO commitees**: dejá el diff visible.

## Pedido (usuario, textual)
"Comenta literalmente lo que ve, yo quiero que opine, y si va a opinar de lo mismo (la imagen es similar
o exactamente igual a lo que ya vio antes) entonces no me sirve."

## Estado actual
1. **El caption que se pide al VLM es un inventario literal y en inglés**
   (`static_vision_plugin.py`, sección de armado de prompt):
   ```
   Describe what happens across these N screen frames (oldest to newest: t+0.0s, t+4.0s).
   One short timestamped description.
   ```
   No pide nada opinable ni destaca lo que importa; el VLM devuelve una enumeración.
2. **La instrucción de turno** que agregó fix-109 (`voices/base.py::frame_look_at_turn`) dice "comentá lo
   que ves en 1 o 2 frases" — con eso el modelo **repite** el caption, que es justo lo que el usuario no
   quiere.
3. **No hay ninguna noción de "ya vi esto".** El plugin dedupea frames *dentro* de la ventana, pero entre
   ventanas no compara nada: con la pantalla quieta (estudiando) narra la misma escena cada 30 s,
   gastando una llamada al VLM cada vez.

## Fix esperado
1. **Pedir material opinable al VLM, en español, sin inventar** (el VLM aporta los hechos; la voz aporta
   la opinión). Reformular el prompt para que pida: qué se ve (breve) + **qué llama la atención** /
   qué cambió respecto de lo anterior si se le pasa ese dato. Sigue prohibido inventar.
2. **La voz opina, no transcribe.** Ajustar la instrucción de turno (`frame_look_at_turn`): que la
   respuesta sea **una opinión/comentario en personaje** sobre lo que ve (qué le parece, qué le llama la
   atención, qué haría o preguntaría), y explícitamente **que no repita la descripción literal** ni
   enumere lo que ya está en el caption. En el idioma configurado (como ya está).
3. **Si la imagen es (casi) la misma que la última que narró, no narra y no llama al VLM.**
   - Guardar la última ventana narrada por fuente: un hash perceptual (dHash/pHash de 64 bits del frame
     representativo) **y** el texto del último caption.
   - Al pedir una narración periódica: calcular el hash de la ventana actual y comparar (distancia de
     Hamming) contra la última narrada; si está por debajo del umbral ⇒ **no** se llama al sidecar/VLM y
     no se emite narración (log `info`/`debug` con el motivo y los bits de diferencia).
   - Umbral configurable (`vision_repeat_hamming_max`, default ~6 de 64) y también un chequeo de texto:
     si el caption nuevo es casi idéntico al anterior (similitud alta), no narrar.
   - **Un look-at pedido por el usuario siempre contesta**, aunque la imagen sea la misma (ahí el usuario
     pregunta algo puntual).
   - Bajo consumo: el camino "no cambió" no puede costar una llamada al VLM.
4. Que sea observable: el log tiene que decir si narró, si se calló por imagen repetida (con el motivo
   numérico) y qué caption usó.

## Tests (obligatorios)
- Misma pantalla dos ticks seguidos ⇒ el segundo **no** emite `generate` de narración y **no** llama a
  `describe_images` (fake del sidecar: cero llamadas), con log del motivo.
- Pantalla distinta ⇒ narra normalmente.
- Caption casi idéntico con frames distintos ⇒ no narra (segundo criterio de texto).
- Look-at pedido por el usuario con imagen repetida ⇒ **sí** contesta.
- La instrucción de turno nueva pide opinión y prohíbe repetir la descripción literal (assert literal).
- El prompt al VLM está en español y pide lo que llama la atención.
- Los tests existentes de visión/voces siguen verdes.

## Docs
- Bug nuevo (id siguiente) con el pedido del usuario y la mecánica (hash + umbral + capa de texto).
- `plugins/vision.md` + `known-issues.md`.

## Verificación (números exactos, sin `| tail`)
1. `.venv/bin/python -m pytest kateto/tests/ -q -k "vision or voice or prompt"`
2. `.venv/bin/python -m pytest kateto/tests/ -q` — baseline: **541 passed / 3 failed** (preexistentes)
3. `git diff --stat`
4. En el resumen: el prompt nuevo al VLM y el texto nuevo de la instrucción de turno, literales.

## Prohibido
- Commitear. Subagentes/task. Tocar la config del usuario. Cambiar el camino de "look-at pedido".
- Inventar contenido: el VLM describe, la voz opina sobre eso; nada de rellenar con lo que no está.
