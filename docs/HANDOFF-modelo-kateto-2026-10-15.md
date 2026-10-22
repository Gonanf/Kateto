# Handoff técnico — El modelo de Kateto (RWKV-7)

**Para:** un consultor externo, senior en entrenamiento y evaluación de LLMs.
**De:** el equipo local (una sola máquina, GPU de 4 GB).
**Fecha:** 2026-10-15.

**Supuesto de lectura:** no conocés este proyecto ni su historia. Todo lo que necesitás para
responder está en este documento; si algo no está, no lo inventes: preguntá.

---

## 0. Qué te pido, y qué no

Te pido **diagnóstico y recetas**, sostenidos en el material que sigue y en tu experiencia con
modelos chicos. Concretamente: donde digas "esto se arregla con X", decime **qué evidencia de este
documento lo sostiene** y **qué experimento barato lo falsificaría**.

Lo que no me sirve: generalidades de manual sobre fine-tuning, ni "depende de tus datos" — los datos
están acá abajo. Si la respuesta honesta es "no se puede saber sin correr X", esa también es una buena
respuesta: decime cuál es X.

---

## 1. El objetivo

Kateto es una entidad digital rioplatense, con voz propia: opina, tiene humor seco, no es un asistente
servil ni responde con libretos de atención al cliente. El registro objetivo es **español rioplatense
con voseo pleno** (*tenés*, *mirá*, *che*, *de una*), frases cortas, cero spanglish.

El modelo tiene que hacer **dos cosas a la vez**: conversar como Kateto y emitir **llamadas a
herramientas** estructuradas (`<tool_call>{...}</tool_call>`) cuando corresponde.

Restricción dura: corre **local**, sin API, en hardware doméstico. No hay presupuesto de nube salvo
una cuenta gratuita de Kaggle.

---

## 2. La arquitectura que usamos hoy

**Base:** RWKV-7 (RNN lineal, sin atención, estado recurrente constante). La escalera oficial de
tamaños es 0.1 / 0.4 / 1.5 / 2.9 / 7.2 / 13.3B. Lo que usamos:

| Rol | Modelo | Contexto preentrenado |
|---|---|---|
| Base principal | `rwkv7-g1j-1.5b` | 16k |
| Base alternativa | `rwkv7-g1k-1.5b` | 25.6k |
| Corridas grandes | `rwkv7-g1j-2.9b` | 16k |

**Entrenador:** RWKV-PEFT (soporta SFT, ORPO y `infctx` para contexto largo por chunks).

**Dos mecanismos de adaptación, deliberadamente separados:**

1. **Pesos (PiSSA / LoRA).** Para el dominio: la sintaxis de las herramientas, el español general,
   el conocimiento del mundo. Los adaptadores se **fusionan** al checkpoint (`.pth` de ~2,85 GB para
   el 1.5B).
2. **State-Tuning (S0).** Se congelan el **100 %** de los pesos y se entrena únicamente el **estado
   inicial** `S0` (≈1,6 M de parámetros, ≈6 MB por voz). Como la memoria de un RWKV es un tensor de
   estado, la personalidad se modula inyectando otro `S0` al arrancar la inferencia: **cambio de voz
   en caliente, sin tocar un peso**. Las voces actuales: `seco`, `streamer`, `doktor`, `jane`,
   `whisperer` (más la voz "operativa" del runtime).

También existe un módulo propio, **ROSA** (optimización robusta para aumentar el estado), pensado para
desacoplar el estado de identidad persistente del estado dinámico que se acumula durante una tarea
larga. Está implementado, no está validado con corridas comparativas.

Un handoff previo del proyecto (septiembre) describe esta misma arquitectura montada sobre el
**0.4B**; todo lo de abajo es la etapa posterior, ya sobre 1.5B y 2.9B.

---

## 3. Los datos

### 3.1 Qué hay hoy en disco

| Archivo | Filas | Peso |
|---|---|---|
| `kateto_v2_combined_train.jsonl` | 9.044 | 19 MB |
| `kateto_v2_combined_eval.jsonl` | 476 | 1 MB |
| `rwkv_kateto_base_train.jsonl` | 20.506 | 9 MB |
| `rwkv_kateto_base_train_plus.jsonl` | 55.137 | 59 MB |
| `rwkv_kateto_base_train_plus.fmtA.jsonl` | 39.378 | 36 MB |
| `hermes_qa_7k.jsonl` | 7.000 | 21 MB |
| `kateto_qa.v2-3k.jsonl` | 3.000 | 3 MB |
| `youtube_asr_dataset.jsonl` | 2.503 | 3 MB |
| `kateto_qa.jsonl` | 500 | 0,5 MB |
| `debate_speech.jsonl` | 800 | 0,4 MB |
| Por voz: `doktor` / `jane` / `seco` / `streamer` / `whisperer` | 550 / 500 / 480 / 500 / 350 | — |
| `toolcalling_kateto_v2.jsonl` | 165 | 0,2 MB |
| `toolcalling_sft.jsonl` | 200 | 0,4 MB |

Hay además dos versiones del mismo corpus: `.jsonl` y `.fmtA.jsonl`. **`fmtA` es el formato que
coincide con la máscara de pérdida** que usa el entrenador; el otro existe por compatibilidad y si se
mezclan, el modelo aprende a predecir los marcadores de rol en vez del contenido.

### 3.2 Forma de una muestra

```json
{"query": "Bueno, empieza el tutorial con los nuevos arreglos",
 "response": "<tool_call>\n{\"name\": \"todo\", \"arguments\": \"{\\\"todos\\\": [...]}\"}\n</tool_call>"}
```

Es decir: pares `query` / `response`, con las herramientas embebidas como texto en `response`. Un
turno, no una conversación armada — la conversación se arma fuera.

### 3.3 Cómo se generan

- El **teacher** es un modelo grande externo, servido por un pool HTTP local; cuando el pool está seco,
  hay un respaldo por CLI. **El teacher no arma la conversación**: se le pide un turno y los turnos se
  concatenan por código. Cuando el teacher armaba la conversación completa, el resultado tenía una
  forma que no era la de una charla real.
- **El validador es por escenario, no global.** Cada escenario (charla, herramienta, silencio, debate,
  roleplay, contexto largo) tiene sus reglas propias. Toda regla nueva se agrega por escenario: los
  validadores globales terminan midiendo la cosa equivocada.
- Hay **pares `chosen` / `rejected`** construidos a propósito **anti-sicofancia** (la respuesta
  obsequiosa como rechazada), pensados para ORPO/DPO.
- Reglas de forma que el dato tiene que respetar: **brevedad** (lo corto es humano; las respuestas
  largas se marcan como rechazadas por defecto), voseo, cero spanglish, y una regla de **contaminación
  de forma**: el modelo no debe aprender los marcadores internos del validador.

### 3.4 Corpus

El corpus de contexto largo son **streams, videos y podcasts del dueño**. Nunca material de clientes.

---

## 4. El entrenamiento

### 4.1 Recetas exactas (las que están en uso)

**ORPO** (`orpo.yaml`):
```
lambda_or: 0.1     lr: 5.0e-05     epochs: 2     batch: 1     accum: 8
```

**PiSSA sobre el 2.9B** (`pissa_2.3b.yaml`):
```
model: base/rwkv7-g1j-2.9b-...pth     n_layer: 32   n_embd: 2560   peft: pissa
pissa_r: 32    svd_niter: 4           ctx_len: 512  micro_bsz: 1
epoch_steps: 750   epoch_count: 2     lr: 2.0e-04 → 2.0e-05
fallback: lora {r: 16, alpha: 32, dropout: 0.01}
```

**State-Tuning** (`state_tuning.yaml`):
```
optimizer: adamw     lr: 1.0e-02 → 1.0e-04 (cosine, warmup 50)
weight_decay: 0.0    s0_l2_gamma: 5.0e-4     # L_total = L_CE + gamma * ||S0||^2
epochs por voz: doktor 15 · jane 12 · whisperer 10 · streamer 15 · seco 5
```

Nota: el `lr` del state-tuning es **agresivo a propósito** (1e-2 con cosine) porque hay que desplazar
el atractor dinámico, no ajustar pesos.

### 4.2 Hardware y sus techos, medidos

- **Local:** una GPU de 4 GB (RX 6500XT, gfx1034). La placa es ~4,2× el CPU para un 4B (34,3 tok/s en
  Vulkan contra ~8 en CPU), y la inferencia llega a **139 tok/s** con el 1.5B a chunk 256.
- **Lo que entra:** un 0.4B completo (≈2,1 GiB en entrenamiento); un **1.5B entra al filo** — a ctx 256
  sobre 4 GB, **la época 1 cierra sana (loss 2,07 → 0,62) y la 2 muere al arrancar por `HIP out of
  memory`**. El 2.9B fusionado pesa 9,25 GB: **no entra**, va a Kaggle.
- **Kaggle 2×T4**, con techo de **12 h por corrida**. Ahí van las corridas grandes.
- El "0.5B" no existe en RWKV-7: la escalera salta de 0.4 a 1.5.
- La conversión a GGUF del propio RWKV afinado **no es un camino directo** (el convertidor espera
  nombres de tensores estilo `fla-hub` y el checkpoint de RWKV-PEFT usa `emb.weight` / `blocks.N.*`).
  El runtime propio sirve el `.pth` nativo; para comparar contra la base oficial sí se usa un GGUF.

---

## 5. La evaluación — y por qué desconfiamos de ella

### 5.1 La vara de estilo (lo que sí está automatizado)

Un archivo de patrones, cada uno con el motivo por el que existe (todos son defectos medidos, no
gustos):

| Métrica | Qué castiga |
|---|---|
| `slop_opening` | Aperturas de manual: *Claro*, *Por supuesto*, *Excelente pregunta*, *Estoy aquí para ayudarte* |
| `reflexive_question` | Ofrecer ayuda en vez de actuar: *¿querés que…?, ¿hay algo más…?* — el vicio central |
| `list_format` | Se mide por **proporción de líneas** (umbral 0,40), no por match: las listas son formato de bot |
| `not_x_but_y` | *No es X sino Y*, la muletilla más reconocible de texto generado |
| `hedge_close` | Cierres de manual: *En resumen*, *Espero que te sirva* |
| `think_leak` | Razonamiento filtrado a la respuesta visible, y encima **en inglés** |
| `voseo` | Sube = más rioplatense. Es el registro objetivo |

Un detalle que costó una corrida: el patrón de apertura necesita un `\s*` inicial **obligatorio**,
porque el texto decodificado arranca con un espacio y el patrón nunca matchea. Medíamos 0,00 sobre
una respuesta que empezaba con *"¡Hola! ¿Cómo estás?"*.

### 5.2 La evaluación de conversación, y su problema

`eval_v2.json`: **30 ítems**, mide **tasa de silencio** y respuestas cortas. Resultado de la última
corrida: **0 silencios sobre 30, 0 respuestas cortas**. Verde.

Y acá está el problema, con una muestra real de ese mismo archivo:

> **Prompt:** *"Che Kateto, contame quién sos"*
> **Respuesta:** *"Soy Kateto. Un compañero directo y seco de lenguaje, sin libretos personales. Te
> respondeo con postura y noticiencias del código, no con faros de la empresa."*

**La métrica no distingue hablar de hablar bien.** Un modelo que emite papilla fluida saca 30/30. Hoy
la única defensa contra eso es que el dueño lo lea a ojo.

### 5.3 Lo que medimos con la batería real (y es el hallazgo central)

Sobre el SFT del 1.5B, con una batería de items de contenido:

> **El registro se aprende. El conocimiento no.**

El modelo toma la voz, el voseo, la brevedad y las herramientas. Cuando se le pregunta por contenido
concreto, inventa o derrapa: pregunta por un hermano y responde *"Soy tu hermano, tenemos dos hermanos
mayores…"*. Nuestra lectura es que **es el techo del 1.5B, no del motor** — pero eso es una hipótesis,
no una medición (ver §6).

### 5.4 Contexto largo

`infctx` existe y corre (chunk 256, 256k declarados; el límite real es el dato, no el modo). Para
medir retención antes de entrenar armamos un **held-out de contexto largo**: se toman los documentos
más largos, se recorta a ~2000 tokens iniciales y se elige **de forma determinista** (regla, no
criterio) una entidad/fecha/número de los primeros ~200 tokens para preguntar por ese detalle, y se
descarta el ítem si ese token aparece también en los últimos ~500. Sin esa última regla, el set mide
memoria de corto plazo y da falsos positivos.

---

## 6. Lo que está medido, y lo que es supuesto

**Medido (con evidencia en disco):**
- El registro se aprende y el conocimiento no, sobre el SFT de 1.5B.
- Una época sobre 4 GB con un 1.5B; la segunda muere por OOM.
- 34,3 tok/s en Vulkan contra ~8 en CPU para un 4B; 139 tok/s del 1.5B a chunk 256.
- Tasa de silencio 0/30 en `eval_v2`.
- La contaminación de forma del validador es real y se purga midiendo.

**Supuesto / sin medir (no lo tomes como hecho):**
- Que el techo sea de capacidad y no de dato. **No lo probamos.** Sería un experimento: misma receta,
  mismo dato, 0.4B vs 1.5B vs 2.9B, y ver si la curva de conocimiento se aplana o sigue subiendo.
- La calidad en general: no hay juicio humano sistemático, ni held-out de contenido con respuesta
  verificable, ni comparación contra la base sin fine-tune con la misma vara.
- ROSA: implementado, sin corrida comparativa.
- El estado de las voces por `S0`: hay checkpoints por voz, no hay evaluación de si la voz se mantiene
  bajo presión conversacional larga.
- Los números de la base oficial (para comparar) no están medidos con nuestro set.

---

## 7. Las preguntas

**P1 — Techo de capacidad o hueco de dato.** Medimos que el registro entra y el conocimiento no. Con
esta escala (1.5B), esta cantidad de data (~55k pares, mezcla de QA, tool-calling, debate y voz) y esta
receta: ¿qué parte del gap cierra más dato y qué parte sólo cierra más parámetros? ¿Cómo se diseña el
experimento de dos horas que lo distingue, sin ir a Kaggle?

**P2 — Cómo se evalúa esto sin el oído del dueño.** Nuestra vara automática mide silencios y slop, y
un modelo papilla fluida la pasa perfecta. ¿Qué familia de métricas automáticas correlaciona de verdad
con el juicio humano para este tipo de objetivo (voz/personalidad + contención de contenido), y cómo
se arma el held-out de contenido para que no se contamine por construcción? Nos importa el costo: la
métrica tiene que poder correr después de cada corrida, no una vez por mes.

**P3 — La receta cuando hay una sola pasada.** Con 4 GB y un 1.5B, la segunda época muere. Si el
presupuesto es una pasada: ¿conviene maximizar tokens únicos, o reducir el dato y dar más vueltas, o
armar currículum? ¿Se puede predecir desde la curva de las primeras ~200 steps si esa corrida va a
aprender algo, o es a ciegas hasta el final?

Dato para P3: `lr 5e-5` con `lambda_or 0.1` en ORPO (2 épocas), y `lr 1e-2 → 1e-4` cosine para el
state-tuning, con `s0_l2_gamma 5e-4`.

---

## 8. La pregunta abierta (la que más me interesa)

**Con todo esto sobre la mesa —arquitectura, dato, receta y vara de medición—: si tuvieras que elegir
UNA sola cosa para cambiar, ¿cuál es, qué evidencia de este documento la sostiene, y qué experimento
de una tarde la falsaría?**

Y si además pudieras tirar una sola pieza de todo el pipeline (una receta, un set de datos, una
métrica, un mecanismo como el state-tuning), **¿cuál tirás y por qué?**

---

### Anexo: dónde vive cada cosa

- Repo del proyecto: `~/proyectos/OpenaiBuildWeek/Kateto` (el runtime corre desde el worktree
  `kateto-wts/merge-master`).
- Corpus y datasets de la corrida: `/run/media/chaos/secundario/harness-run/kt-r14/data/`.
- Checkpoints: `kaggle-out2` (3 GB, ok) y `harness-run/kaggle-v3-out/` (`kateto-1.5b-v2.pth`, 2,85 GB).
  Ojo: `kaggle-out` está en **0 bytes**, no usarlo.
- Corpus público de muestra: `/run/media/chaos/secundario/proyectos/kateto-train-public/samples/`.
- Recetas: `kt-r14/config/{orpo,pissa_2.3b,state_tuning}.yaml` y `behavior_patterns.yaml`.
- Handoff previo (etapa 0.4B, septiembre): `kt-r14/HANDOFF.md`.
