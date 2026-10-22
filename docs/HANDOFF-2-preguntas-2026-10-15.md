# Handoff 2 — Preguntas para el modelo grande (implementación de las correcciones)

**Contexto:** este documento sigue al handoff `HANDOFF-modelo-kateto-2026-10-15.md` (estado del modelo
RWKV-7 de Kateto: arquitectura, datasets, recetas, evaluación), que ya fue respondido por un modelo
senior. Abajo va **qué se decidió aplicar de esa respuesta** y **las preguntas nuevas** que aparecieron
al planear la implementación. No conocés el proyecto: lo mínimo necesario está acá.

## 0. Resumen en cinco líneas

Kateto es una entidad digital rioplatense sobre RWKV-7 (1.5B). Se entrena con pares
`query/response` sintéticos generados por un teacher grande, con PiSSA/LoRA sobre los pesos y
state-tuning (`S0`, 6 MB) para las voces. El síntoma medido: **el registro se aprende, el
conocimiento no**, y las respuestas salen con "papilla fluida" (*"Te respondeo con posturitas del
código"*). El diagnóstico que recibimos apunta a datos y receta, no a capacidad del 1.5B.

## 1. Lo que ya decidimos aplicar (no hace falta que lo re-justifiques)

- **Sacar el ASR del SFT.** El `youtube_asr_dataset.jsonl` (2.503 líneas de transcripciones de
  streams del dueño) entra hoy al dataset de entrenamiento. La hipótesis recibida: sus errores
  fonéticos enseñan a inventar palabras, sus muletillas + el filtro de voseo producen el voseo
  caricato, y —el punto que más nos cerró— **el dueño habla en primera persona, así que entrenarlo
  como `response` le enseña al modelo que él es el dueño** (de ahí que diga que tiene hermanos).
- **Bajar el régimen de entrenamiento.** PiSSA a `lr 1e-5` (venía de `2e-4`), `r=16`, 400 steps, y
  **parar antes**: la corrida anterior terminó en loss **0,62**, que según la devolución es
  overfitting severo (probabilidad media del token exacto ≈ 54 %). El objetivo es frenar cerca de
  **1,25**.
- **State-tuning y ROSA en pausa.** `S0` venía entrenándose a `lr 1e-2` por hasta 15 épocas sobre
  350-550 líneas; se congela ROSA y el state-tuning baja a 3-5 épocas, y recién después de que la
  base esté sana.
- **Arreglar el OOM de la época 2**, que no es del entrenamiento sino del cierre de época
  (`empty_cache()`, `gc.collect()`, `state_dict` a CPU antes de guardar,
  `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`).
- **Métricas nuevas**, tres y baratas: ΔPPL de las respuestas generadas contra el **modelo base sin
  fine-tune** (los neologismos dan pico de pérdida), tasa de OOV contra un diccionario `es_AR`, y
  fidelidad por slots (`must-include` / `must-not-include`) + similitud con embeddings.

## 2. Las preguntas nuevas

Son las que me impiden escribir la receta final. Todas apuntan a **cómo se hace operable** lo que
ya aceptamos como dirección.

**Q1 — Cómo se corta la fuga de identidad sin perder el estilo.** La devolución dice "usá los streams
del dueño solo como inspiración de estilo, o reescribilos con un teacher limpio". Necesito la parte
operable: ¿qué fracción de un stream es recuperable, y con qué regla determinista se separa *estilo*
de *biografía*? ¿Se puede hacer por reescritura automática (teacher que reescribe en tercera persona
manteniendo el registro), o el material oral es directamente inviable para SFT y solo sirve para
derivar reglas de estilo que después se aplican a datos sintéticos?

**Q2 — Conversaciones encadenadas con un teacher sin memoria.** Se nos señaló que concatenar turnos
generados de a uno rompe el estado recurrente (cada turno fue escrito sin el histórico real). Para
armar conversaciones de 4-6 turnos donde el turno N referencie al turno 1: ¿se le pasa el histórico
completo al teacher en cada llamada (y se acepta el costo, con el riesgo de que "arregle" el pasado),
o se pide la conversación entera en una sola generación (y se pierde control por turno)? ¿Hay una
tercera vía que use bien el estado de un RWKV?

**Q3 — El número 1,25.** ¿Es un valor de este dataset y este modelo, o hay una regla general para
fijar el punto de parada? ¿"Loss de validación dejando de bajar", "un múltiplo del loss inicial",
"perplejidad objetivo"? Pregunto porque el presupuesto es de una sola pasada: si el criterio es
"mirá la curva", necesito saber qué miro y en qué momento corto sin quemar la corrida.

**Q4 — El umbral del ΔPPL.** La métrica es clara en el mecanismo (pasar las respuestas por el modelo
base y ver el pico de pérdida), pero ¿contra qué se compara un valor concreto para declarar "esta
corrida rompió la gramática"? ¿Percentil 95 de la pérdida por token en la base, un delta absoluto
respecto de las respuestas humanas de referencia, un ratio? Si tenés un número de la práctica, mejor
que una fórmula.

**Q5 — Cómo se mide la voz, no solo la corrección.** Las tres métricas miden gramática, léxico y
fidelidad de contenido — pero nuestro objetivo es una **personalidad**. ¿Hay forma objetiva de medir
"suena a ella" que no sea un juez LLM con su propio sesgo? Pensamos en entrenar un clasificador
chico con los pares `chosen`/`rejected` que ya tenemos (respuesta en personaje vs respuesta de
asistente genérico); ¿es una buena idea o hay una trampa conocida (el clasificador aprende longitud,
formato o palabras del validador en vez de la voz)?

**Q6 — ¿El objetivo final es el contexto, no los pesos?** El experimento de grounding que nos
propusieron (100 pares con y sin ficha de hechos in-context) sugiere que el conocimiento debería ir
en el contexto y el modelo solo aprender registro y forma. Si es así: ¿el SFT de conocimiento
(55k pares de QA) es directamente un error de diseño, o sirve como "pre-entrenamiento de dominio"
siempre que los hechos concretos no dependan de los pesos? ¿Qué proporción del dataset debería ser
conversación pura vs conocimiento?

**Q7 — State-tuning sobre una base ya tocada.** Se nos advirtió que inyectar un `S0` entrenado a
`lr 1e-2` sobre pesos ya movidos por PiSSA satura las activaciones. ¿Cómo se **verifica** eso antes
de servir el modelo, con una métrica? (Nos gustaría un chequeo pre/post inyección, no confiar en el
ojo.)

**Q8 — Dónde entra ORPO en la receta nueva.** Tenemos ORPO implementado (`lambda_or 0.1`, 2 épocas) y
pares anti-sicofancia. Con la receta conservadora (lr 1e-5, 400 steps, parada temprana): ¿ORPO va
después del SFT, mezclado, o se posterga hasta que la base esté sana? Y si va después: ¿el `lr` y el
`lambda_or` se mantienen o se re-escalan junto con el resto?

## 3. Qué voy a hacer mientras tanto

Lo que no depende de tus respuestas ya está en marcha:

1. Sacar el ASR del armado del dataset (`prepare_datasets.py`) y medir cuántas líneas caen.
2. Implementar las tres métricas de calidad como script que corre después de cada corrida.
3. Aplicar el fix del OOM y las recetas conservadoras, para poder entrenar el 1.5B en la GPU local
   de 4 GB (RX 6500 XT, gfx1034) — que es el objetivo de esta ronda.

Lo que sí depende: **Q2, Q3 y Q6** cambian qué dataset construyo; **Q4, Q5 y Q7** cambian qué
métricas implemento; **Q8** cambia el orden de las corridas. Si tenés que priorizar, Q2 y Q6 valen
más que el resto: son las que deciden si rehago el dataset o no.
