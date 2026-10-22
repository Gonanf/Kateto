# Handoff 3 — Ejemplos reales del dataset + las preguntas que quedaron

**Contexto:** seguimos con el modelo RWKV-7 de Kateto. Este documento cierra el ciclo de preguntas
anteriores (handoffs 1 y 2) y trae **muestras textuales del dataset real** más las dudas nuevas que
aparecieron al mirarlas. Los dos handoffs anteriores ya fueron respondidos y sus correcciones están
en implementación.

## 0. Lo que ya está en marcha (no hace falta que lo revises)

- ASR fuera del armado del dataset, con filtro determinista de contaminación de perspectiva
  (respuesta en 1ª persona con biografía del dueño).
- Script de métricas post-corrida: ΔPPL contra el modelo base, OOV contra diccionario `es_AR`,
  fidelidad por slots.
- Fix del OOM de fin de época + régimen conservador (PiSSA `lr 1e-5`, `r=16`, 400 steps, parada
  temprana, ORPO postergado, `S0`/ROSA congelados).

Todo eso sale de tus respuestas anteriores. **Lo que sigue es nuevo y sale de mirar el dato de verdad.**

## 1. Las muestras (textuales, del dataset que se usa hoy)

### 1.1 `kateto_qa.v2-3k.jsonl` — 3.000 filas

Muestra 1 (el campo `question` es el **prompt del generador**, no una pregunta):

```json
{"question": "Okay, the user wants me to create a question that's coherent with the given answer. The answer is: \"Add to the kanbam random items, and create an agent for hermes.\" Let me break this down.\n\nFirst, \"kanbam\" is likely a typo for \"Kanban,\" which is a project management tool..."}
```

Muestra 2 (etiqueta de moderación como pregunta, respuesta vacía de contenido):

```json
{"question": "User Safety: safe", "answer": "[Soloto] hola ,", "source_label": "answer", "generated": true, "align": "ok", "judge": null}
```

### 1.2 `youtube_asr_dataset.jsonl` — 2.503 filas (el ASR que estamos por sacar)

```json
{"question": "Transcribí el audio en español rioplatense:\n\"bueno, tremendo bueno, vamos a ver lo que estaba lo que estuve haciendo durante estos días fue básicamente que estuve implementando open project al probotowner...\"",
 "answer": "Bueno, tremendo Bueno, vamos a ver Lo que estaba Lo que estuve haciendo Durante estos días Fue bási..."}
```

### 1.3 `kateto_v2_combined_train.jsonl` — 9.044 filas (esta parte sí parece sana)

```json
{"query": "Hace solo la tarea", "response": "<tool_call>\n{\"name\": \"read_file\", \"arguments\": \"{\\\"path\\\": \\\"/home/chaos/proyectos/pj/internal/model/item.go\\\"}\"}\n</tool_call>", "source_label": "hermes-tool-call"}
```

## 2. Las preguntas nuevas

**Q1 — El `question` contaminado: ¿se rescata o se tira?** En `kateto_qa.v2-3k` hay filas cuyo campo
`question` es el *meta-prompt del generador en inglés* ("Okay, the user wants me to create a question
that's coherent with the given answer...") y otras donde es una etiqueta de clasificador
("User Safety: safe") con una respuesta sin contenido. ¿Hay forma determinista de separar esas filas
del material legítimo (por ejemplo, detectar `question` que arranca con inglés meta-conversacional o
con etiquetas del pipeline), o la regla es tirar el archivo entero y regenerar? ¿Cómo se detecta ese
tipo de contaminación **antes** de que entre al dataset, en el armado?

**Q2 — El ASR no es conversación, es una tarea de transcripción.** Mirá la muestra: no son turnos de
charla, son pares del tipo *"Transcribí el audio en español rioplatense: …"* cuya respuesta es la
transcripción con mayúsculas raras (el artefacto del reconocedor). Con ese material, ¿la receta de
recuperar ~400 líneas con filtro anti-biografía + back-translation sigue aplicando (extrayendo las
frases *dentro* de las transcripciones), o el formato de origen lo descalifica directamente?
Pregunto porque el filtro que nos diste apunta a líneas de charla, y acá la unidad es un tramo de
audio transcripto.

**Q3 — Tenemos ~3 millones de tokens de ORPO y tu objetivo era 6-8k muestras. ¿Cómo se reconcilian?**
El dueño del proyecto dice que juntando otros datasets hay del orden de **3 millones de tokens**
para ORPO. Tu propuesta de mezcla apunta a ~6.000-8.000 muestras de alta calidad (que a ~100 tokens
por muestra son menos de un millón de tokens). Las dos cosas no pueden ser el objetivo al mismo
tiempo: ¿el techo de 6-8k es un techo de *calidad* (más dato diluye) o de *presupuesto de
entrenamiento* (una pasada en 4 GB)? Si hay 3M de tokens disponibles, ¿conviene usarlos en ORPO, en
SFT, o repartirlos? ¿Y cambia la receta de parada temprana cuando el volumen sube?

**Q4 — De dónde salen los contextos del QA grounded.** La propuesta de convertir el QA huérfano en
QA con grounding (70 % de las muestras con el dato inyectado en un bloque de contexto, 30 % con un
contexto que *no* tiene el dato y respuesta de abstención seco) es clara en la forma — pero no en la
fuente. ¿Ese bloque de contexto se construye a mano por entidad, se genera con el teacher a partir de
un índice de hechos, o se extrae de documentos reales? ¿Y cómo se elige el hecho que va en cada una de
las 70 %, para no terminar con el mismo dato repetido en cientos de filas?

## 3. Una observación por si cambia algo

En `kateto_v2_combined_train.jsonl` los pares buenos vienen con `source_label` (`hermes-tool-call`,
etc.) y duplican la información en cuatro claves (`query`/`response` y `question`/`answer` con el
mismo contenido). Si el grounding y la proporción se van a recalcular, quizás convenga decidir **un
solo esquema de campos** ahora y no arrastrar los dos: ¿alguno te parece más sano para el
`loss_mask` que ya usamos (`fmtA`)?
