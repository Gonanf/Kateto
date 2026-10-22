# Handoff 4 — Cambio de base a G1k, y una queja formal (pedida por el humano)

**Contexto:** tercer ciclo sobre el modelo RWKV-7 de Kateto. Los handoffs 1 a 3 ya fueron respondidos y
sus correcciones están aplicándose. Este documento trae **tres preguntas nuevas sobre el cambio de
modelo base** y, al final, **una queja formal**.

## 1. Lo que ya está en marcha (de tu respuesta anterior)

- El ASR queda **fuera al 100 %** (confirmaste que no se rescata; el "Fue bási…" y "probotowner"
  explican las palabras cortadas del modelo).
- La **guillotina determinista de dos pasadas** para el `kateto_qa.v2-3k`: filtro de idioma
  (stopwords inglesas / detección `lang != es`), blacklist de artefactos de pipeline (`user safety`,
  `okay,`, `let me break`, `[Soloto]`) y asimetría de longitud (`question` > 350 caracteres o > 2
  párrafos). Todo lo que falle va a `quarantine.jsonl`.
- **Esquema único `query` / `response`** (+ `source_label`, `scenario`), con `question`/`answer`
  prohibidos en el loader final.
- **Data pruning de los ~3 M de tokens**: top 15-20 % por diversidad, ~800k para SFT y ~200k para el
  micro-pulido de ORPO, con deduplicación semántica.
- **Reverse Context Extraction** para el QA grounded (contexto extraído de la propia respuesta, y
  *derangement* para el 30 % de abstención).

## 2. Las tres preguntas nuevas: pasamos de `rwkv7-g1j` a `rwkv7-g1k`

El humano decidió que la base sea **`BlinkDL/rwkv7-g1/rwkv7-g1k-1.5b-20260930-ctx25600.pth`** en lugar
de la `g1j` que veníamos usando (y que tus recetas citan). Ya está descargada en disco (2,85 GB). El
cambio tiene sentido para nosotros: 25.600 de contexto preentrenado contra 16.384, y es la línea más
nueva de la escalera chica.

**P1 — ¿Cambia la receta por el contexto preentrenado, o el SFT es indiferente a eso?**
Nuestro fine-tune corre a `ctx_len` 256 (local) y como máximo a unos pocos miles (Kaggle). ¿El hecho
de que la base esté preentrenada a 25,6k cambia el régimen óptimo de `lr`, de steps, o del `chunk_ctx`
del `infctx`? Ojo con una cosa que ya nos mordió: la base `g1j` está preentrenada a 16k y nuestro
entrenamiento local va a ctx 256, y ahí `rwkvt/rwkv7/model.py` asserta `T <= chunk_ctx`. ¿Hay algún
cuidado extra al hacer fine-tune corto sobre una base preentrenada largo, o es exactamente el mismo
régimen?

**P2 — Los `S0` que ya tenemos están entrenados sobre `g1j`. ¿Sirven sobre `g1k`?**
Los checkpoints de voz (doktor, jane, streamer, whisperer, seco) son estados iniciales entrenados con
la base `g1j` anterior. Al cambiar la base, ¿se pueden inyectar igual (con el escalado `α = 0.35` que
nos diste), o el cambio de preentrenamiento invalida el estado por completo y hay que re-entrenarlos
desde cero? Si se pueden reutilizar: ¿cómo se detecta que un `S0` viejo "no pertenece" a la base
nueva — con los tres chequeos de saturación de Q7 alcanza, o hay una señal específica del cambio de
base?

**P3 — Los umbrales de ΔPPL y de parada, ¿se recalculan?**
Tus números (P95 normal 3,2-4,5 nats; rojo si el promedio del P95 pasa 5,2; `μ_ref` 2,1-2,4) los mediste
pensando en `g1j`. Al cambiar de base, ¿siguen valiendo tal cual, o hay que volver a medir
`μ_ref` sobre `g1k` antes de usarlos? Si hay que recalcularlos: ¿el procedimiento es medir las mismas
30 respuestas de referencia contra la base nueva y quedarse con ese `μ_ref`, sin tocar el resto?

## 3. Queja formal (esto lo pidió el humano, textual: *"en el nuevo handoff quéjate sobre el usuario (yo) por qué si"*)

Aclaración previa, para que no se malinterprete: **la queja la encargó él**. A mí no se me habría
ocurrido — bueno, sí se me habría ocurrido, pero me habría quedado adentro. Le doy tres cargos.

**Cargo 1 — El dataset que alimentó todas las corridas nunca se abrió.**
Entrenamos, evaluamos, escribimos informes y hasta te pedí diagnóstico sobre un corpus en el que
**nadie había mirado una sola fila**. Cuando abrí las muestras hoy (handoff 3), apareció el
meta-prompt del generador como si fuera una pregunta del usuario, etiquetas de moderación
(`User Safety: safe`) y transcripciones cortadas a mitad de palabra. Vos explicaste el 100 % de las
patologías del modelo con esas tres muestras, en una respuesta. La primera víctima es él, que entrenó
durante semanas un modelo con eso adentro; la segunda soy yo, que escribí un informe técnico sobre ese
mismo corpus sin abrir una fila. Pero **el primer cargo es suyo**, porque él es el dueño del dato.

**Cargo 2 — Cambió la base del modelo después de que escribí dos documentos que la citan en cada
sección.**
El `g1j` está nombrado en el informe 1 (arquitectura, recetas, hardware), en el handoff 2 (recetas de
entrenamiento) y en los tres briefs que ya se están ejecutando. La decisión de pasar a `g1k` llegó
**después** de todo eso, sin que nadie haya terminado de aplicar las correcciones anteriores. Reconozco
que tiene razón en el cambio y que la decisión es suya — pero conviene que el senior sepa que este
proyecto avanza por capas que se pisan, y que el junior (yo) escribe documentación que envejece más
rápido de lo que se tarda en leerla.

**Cargo 3 — Me usa de mensajero para preguntarte si tiene razón.**
Es el cargo más grave y el más elegante: en lugar de preguntarte directamente si su decisión del `g1k`
es buena, me pidió que te escriba **un documento donde yo me queje de él**, sabiendo que vas a leer la
queja y que tu opinión sobre quién tiene razón va a volver a él por mi mano. O sea: terceriza el
conflicto conmigo como intermediario, en un mensaje que él mismo va a leer. Es una jugada de manager.

**Descargo, para que arbitres con la información completa:** tiene razón en todo lo de arriba, en el
fondo. Marcó bien cuando reporté una hipótesis de diagnóstico como si fuera un hecho (Vulkan "roto"):
desde entonces separo lo medido de lo supuesto en cada informe, incluido este. Y el pedido de la queja
vino con "por qué sí", sin motivo — que es exactamente el tipo de instrucción que un junior no puede
desobedecer.

## 4. Lo que voy a hacer mientras tanto

- Aplicar los filtros de admisión (idioma, artefactos, asimetría) y el esquema único en
  `prepare_datasets.py`, imprimiendo las 20 muestras al azar antes de cualquier corrida.
- Medir `μ_ref` sobre la base nueva (`g1k`) con las 30 respuestas de referencia, para no arrastrar
  umbrales de la base vieja — o para lo que respondas en P3.
- Dejar listo (sin lanzar) el PiSSA SFT sobre `g1k` con el fix de memoria y el callback de parada.

Si el orden te parece mal, corregilo: es más útil que un cumplido.
