---
title: "Evaluación: los papers de 'sleep' contra Hipotenusa"
description: "Cuatro papers de arXiv, el Sleep Framework de Google y Harness² aplicados a la capa de memoria (Hipotenusa y Korat): qué entra, qué no, y qué experimento probar primero."
---

# Los papers de "sleep" contra Hipotenusa

Evaluación de nov-2026. Criterio: no "¿es interesante?" sino **¿qué parte entra en este repo, en esta máquina, sin tocar el camino de latencia del turno?**

## Dónde vive esto (y dónde no)

Esto **no es material para el clasificador de turno**. `eot_gate` (2 etapas ONNX, ~33 ms CPU, F1 0.645/0.841, fail-open) decide en el camino caliente y queda como está: ninguno de estos papers lo toca, y confundir los dos planos es el error caro.

Lo de "sleep" es un **job de consolidación offline** con dos consumidores posibles:

- **Hipotenusa** (el runtime del celu: un supervisor, sidecar ASR `:8094`, HTTP `:8099`, LLM contra el router `:11434`). Ya tiene de dónde sacar la memoria rápida —`conversation_log` con `logs/session-YYYY-MM-DD.jsonl` y `user_turn` / `voice_turn` / `closed_by`— y a dónde escribirla: la memoria curada por voz, `VoiceMemoryLedger` en `config_dir/memory/{dept}.json`, 200 entradas máximo. El job corre con el celu quieto o cargando y destila el día; cero impacto en latencia porque no toca el turno, y `SoulSnapshotStore` da snapshot + rollback.
- **Korat** (el que corre loops de experimento largos, `finished_pct`, `cierre-turno`). Ahí sleep = al cerrar cada corrida, destilar lo frágil —hallazgos, descartes, parámetros que no anduvieron— en priors estables (los OKF reports). Es el mismo patrón con otro insumo, y el guardrail de plasticidad de §2 pega de lleno: tope de refreshes y set congelado.

Lo que ya existe y no se negocia: `eot_gate` (2 etapas ONNX, ~33 ms CPU, F1 0.645/0.841, fail-open, presupuesto 1 s), `turn_gate` como orquestador, `executor_classifier` para ruteo, LFM3-Omni-2B + LoRA en llama.cpp `:11434`, y `conversation_log` escribiendo `logs/session-YYYY-MM-DD.jsonl` con `user_turn` / `voice_turn` / `closed_by`.

Hardware: RX 6500 XT 4 GB (`gfx1034`, fuera de la lista oficial de ROCm), Iris Xe DG1 Vulkan, i3-10105F, 31 GB. Todo paper que pida entrenar un transformer de 4B–8B queda fuera por defecto; lo único que entra sin trucos es CPU (ONNX) o Vulkan.

## 0. Primero: qué es el "Sleep Framework" de Google

**Existe, y es uno de los cuatro papers.** El blog de Google Research — *"The sleep framework: A new way for LLMs to retain knowledge in continual learning"* (`research.google/blog/the-sleep-framework-a-new-way-for-llms-to-retain-knowledge-in-continual-learning/`) — enlaza directamente a [arXiv:2606.03979](https://arxiv.org/abs/2606.03979). Mismos autores (Behrouz, Hashemi, Javanmard, Mirrokni; Google Research + Cornell). Una versión circula desde sept-2025 en OpenReview. O sea: "Sleep Framework" = "Sleep paradigm" = 2606.03979. Un solo trabajo, tres nombres.

**Pero el nombre es ambiguo**, y conviene decirlo antes de citarlo:

| Frase | Qué es en realidad | Relación con Hipotenusa |
|---|---|---|
| "Sleep Framework" / "Sleep paradigm" | [2606.03979](https://arxiv.org/abs/2606.03979) — consolidación **paramétrica** (MoE + destilación + dreaming) | El paper 1 de esta nota |
| *"Do Language Models Need Sleep?"* | [2605.26099](https://arxiv.org/abs/2605.26099) — pasadas recurrentes **offline** sobre fast weights de bloques SSM | Paper distinto, mismo chiste de título. Paper 4 de esta nota |
| *"sleep-time compute"* | [2504.13171](https://arxiv.org/abs/2504.13171) (Lin et al., Letta) — pensar offline **antes** de la query, sin tocar pesos | Tercer cosa distinta. No estaba en la lista. |

Si alguien dice "el sleep framework" sin número, hay tres candidatos. Citá siempre el arXiv id.

---

## 1. Language Models Need Sleep: Learning to Self-Modify and Consolidate Memories

**arXiv:2606.03979** · Behrouz, Hashemi, Javanmard, Mirrokni · v2 10-jul-2026 · [PDF](https://arxiv.org/pdf/2606.03979)

**Qué propone (3 líneas).** Un ciclo *wake / sleep* para modelos desplegados: durante el wake, el contexto vive en memoria rápida (KV cache, capas de alta frecuencia); al dormir, el modelo (a) abre expertos low-rank nuevos en bloques de memoria lentos para ganar capacidad sin sobreescribir lo viejo, (b) hace *knowledge seeding* — destila la memoria frágil del "yo chico" hacia esos parámetros nuevos con GKD + imitación por RL (reward semántico + distancia de Levenshtein), y (c) *dreaming*: genera un curriculum sintético con RL para practicar lo recién consolidado. Al terminar, resetea la memoria rápida.

**Números publicados.** SQuAD sin contexto, n=200 pasajes: base 31.9 → fine-tune sin dreaming 32.0 → SEAL 43.2 → Sleep 46.2. AIME-24 con Qwen3-8B: base 73.8 → GRPO 76.4 → Sleep 79.2. BABILong estable hasta 10M tokens (con Hope fine-tuneado). La ablación clave: **quitar Dreaming baja SQuAD-200 de 46.2 a 36.2** — casi todo el jugo está en la parte autogenerada. Config declarada: LoRA r=64, α=128, batch 32, 500/100/100 pasos. **GPU-horas: no publicado** (solo relativo: SFT necesita 4.3x/3.6x/4.8x de wall-clock para igualar).

**Qué aplicaría a Hipotenusa.** El *patrón*, no el mecanismo: memoria rápida y barata (los JSONL de `conversation_log`) → consolidación periódica y offline → memoria lenta y curada (`VoiceMemoryLedger`, `config_dir/memory/{dept}.json`, 200 entradas máx, inyectada al inicio de sesión). Es exactamente la misma dirección de flujo, con texto en lugar de pesos. El *mecanismo* (expansión MoE, GKD, dreaming) no entra: requiere entrenar un 8B y esta máquina no lo hace ni de casualidad.

**Coste.** Patrón textual: **4–6 h**. Archivos nuevos `scripts/nightly-consolidate.py` + `scripts/systemd/hipotenusa-nightly-consolidate.{service,timer}` (mismo patrón que `hipotenusa-voice-llm-watchdog`), llamando al llama-server de `:11434` y a `VoiceMemoryLedger.refine()` — cero cambios en código de runtime. Si tiene que vivir en el bus: **8–10 h**, `hipotenusa/plugins/executor/sleep_consolidation.py` + alta en `hipotenusa/plugins/executor/__init__.py` + sección en `config/defaults/config.toml`. Versión paramétrica: no estimable, no publicada, no posible acá.

**Riesgo.** Medio. Es consolidación **no supervisada y nocturna**: un fact mal destilado queda en el ledger hasta que alguien lo borre, y la regla de higiene del ledger prohíbe explícitamente logs de progreso — justo lo que abunda en un JSONL de sesión. Mitigantes que ya existen: `SoulSnapshotStore` (snapshot + rollback), tope de 200 entradas y `evidence` obligatoria. Falta: política de merge/purga, porque consolidar sin podar sólo adelanta la saturación del tope.

---

## 2. Can Scale Save Us From Plasticity Loss in Large Language Models?

**arXiv:2606.24752** · Hernandez-Garcia, Figliolia, Millidge · 23-jun-2026 · [PDF](https://arxiv.org/pdf/2606.24752)

**Qué propone (3 líneas).** Mide la pérdida de plasticidad —la capacidad de seguir aprendiendo— en transformers GPT-style sobre un problema multilingüe continuo construido con CulturaX: 8 idiomas (inglés, chino escrito, francés, japonés, español, alemán, portugués, ruso), **100B tokens de train y 1B de eval por idioma**, ciclados indefinidamente. La sondea con una tarea held-out en vietnamita: cuánto tarda el modelo en adaptarse después de cada ciclo. Encuentra degradación en modelos de **5M a 314M parámetros no-embedding**, cuyo *onset* sigue una ley de escala que crece sublinealmente con el tamaño.

**Números publicados.** 5M–314M non-embedding; 8 idiomas × 100B tokens; probe vietnamita held-out; ley de escala sublineal (el paper no publica una fórmula con coeficientes en las secciones leídas). **GPU-horas: no publicado.**

**Qué aplicaría a Hipotenusa.** Es el **guardrail** del plan de LoRA nocturno, no una feature. Dos consecuencias concretas: (1) escalar (2B vs 314M) *retrasa* el onset pero el paper dice explícitamente que no lo previene — así que "el modelo es grande, aguanta" no es argumento; (2) el fenómeno aparece también en entrenamiento **estacionario**, no sólo con cambios abruptos de tarea, así que refrescar el adaptador con el mismo tipo de dato todos los días también cuenta. Traducción operativa: tope de refreshes, set de eval congelado, comparar antes/después de cada uno, y preferir memoria **no paramétrica** (texto) para todo lo que cambia a diario.

**Coste.** **0 h de código**. 3–4 h para el arnés de eval (`scripts/qa/`, set congelado de utterances held-out) — barato y sirve para cualquier refresh futuro, no sólo LoRA.

**Riesgo.** Bajo como lectura, alto como omisión. El riesgo real es el inverso: refrescar LoRA cada noche sin medir, y descubrir la degradación tres semanas después sin línea base. Salvedad honesta: los modelos del paper son ~3 órdenes de magnitud más chicos que LFM3; extrapolar a 2B es **no publicado**.

---

## 3. In-Place Test-Time Training

**arXiv:2604.06169** · Feng, Luo, Hua, Zhang, He, Huang, Cai (ByteDance Seed + PKU) · ICLR 2026 Oral · [PDF](https://arxiv.org/pdf/2604.06169) · [código](https://github.com/ByteDance-Seed/In-Place-TTT)

**Qué propone (3 líneas).** Convierte la proyección final del MLP (`W_down`) en *fast weights*: `W_up`/`W_gate` quedan congeladas y `W_down` recibe **un paso de gradiente por chunk** de 512–1024 tokens, con un objetivo alineado a next-token-prediction en vez del objetivo de reconstrucción clásico de TTT. Chunk-wise para paralelizar; reset en bordes de documento para no filtrar contexto entre secuencias. Es "drop-in" sobre un LLM preentrenado, sin cambio arquitectónico.

**Números publicados.** Qwen3-4B-Base con continual training (~20B tokens @32k + ~15B @128k, AdamW, LR 5e-6): RULER **128k 74.8 → 77.0**, **256k 41.7 → 43.9**; en 4k–32k la diferencia es ruido (±1). LLaMA-3.1-8B 64k 81.6 → 83.7. **GPU-horas: no publicado** (sí tokens: ~35B en total).

**Qué aplicaría a Hipotenusa.** Prácticamente nada, y decirlo rápido ahorra semanas. Tres bloqueos duros: (1) llama.cpp sirve un GGUF cuantizado — no hay optimizador, no hay backward, no hay forma de escribir `W_down` por chunk; (2) el "drop-in" igual necesita ~35B tokens de continual training antes de que el método exista en los pesos; (3) las ganancias aparecen a **128k–256k de contexto**, y un turno de Hipotenusa no llega ni cerca. Lo único transferible es el argumento de diseño: si vas a adaptar algo, el lugar más barato y legítimo es la proyección final del MLP — que es prima hermana de lo que ya hacen con LoRA.

**Coste.** n/a. Implementarlo en el camino de serving: **no**.

**Riesgo.** Ninguno adoptándolo; alto si alguien lo lee como "podemos tener TTT en el harness". El trap concreto: creer que un paso de gradiente por turno es barato en una máquina con `gfx1034` fuera de la lista ROCm.

---

## 4. Do Language Models Need Sleep? Offline Recurrence for Improved Online Inference

**arXiv:2605.26099** · Lee, McLeish, Goldstein, Fanti (CMU + UMD) · v3 5-jun-2026 · [PDF](https://arxiv.org/pdf/2605.26099)

**Qué propone (3 líneas).** Un mecanismo tipo sueño donde el modelo convierte contexto reciente en *fast weights persistentes* antes de borrar el KV cache: durante el sueño hace **N pasadas recurrentes offline** sobre el contexto acumulado y actualiza, con una regla local aprendida, los fast weights de sus bloques SSM/lineales. La latencia de wake no cambia: el cómputo extra se paga durmiendo. Argumento central: el cuello de botella no es capacidad de memoria sino **cuánto cómputo** se dedica a transformar contexto desalojado en estado interno útil.

**Números publicados.** Arquitecturas SSM-attention híbridas: desde 10 capas d=512 entrenado desde cero hasta Jet-Nemotron 2B (híbrido de Qwen2.5-1.5B) y Ouro 1.4B + 6 capas Jet (<+10% params). Tareas: autómata celular, retrieval multi-hop en grafo, GSM-Infinite. **Cómputo publicado**: autómata <1 GPU-day A6000; Depo y GSM-Infinite ~1–2 GPU-days H100 por corrida (batch 512/128/256).

**Qué aplicaría a Hipotenusa.** Nada directamente: ningún modelo servido acá tiene bloques SSM con fast weights entrenables, y la regla de update es **aprendida**, no una heurística que se pueda portar. Queda una lección de presupuesto, barata de aceptar: el cómputo caro pertenece a la ventana idle, y más cómputo en consolidación compra **profundidad de razonamiento**, no sólo recall. Hipotenusa ya cumple la parte de latencia (33 ms y fail-open); lo que este paper sugiere es que si algún día consolidan, no lo hagan en el turno.

**Coste.** n/a.

**Riesgo.** Ninguno. El riesgo sería confundirlo con el paper 1 y concluir que el "sleep" de Google necesita arquitectura SSM.

---

## 5. Harness²: Recursive Agent Harnessing for an Open World

**arXiv:2610.14224** · Xu, Chen, CuiZhu, Dalvi Mishra, Ming, Yu, Han, Lee, Pfister (Google Cloud AI Research + Northwestern) · [repo](https://github.com/google-research/harness2) Apache-2.0 · [PDF](https://arxiv.org/pdf/2610.14224)

**Qué propone (3 líneas).** Optimiza el *harness* —todo lo que rodea al modelo— manteniendo los pesos congelados. Expone ocho componentes editables: **system prompt, guardrails, memoria, tool guidance, subagentes, skills, scripts y plugins**. Dos recursiones: a nivel tarea hace **Propose–Probe–Compose** (propone ediciones, las prueban executors sobre la misma tarea, y compone el harness refinado comparando *contrastes de comportamiento* sin ground-truth); a nivel harnessing actualiza un **improvement harness** persistente con los harnesses adoptados y las lecciones con evidencia, que guía la próxima tarea.

**Números publicados.** GLM-5 y Gemini 3.5 Flash sobre sus harnesses base: hasta +11.5 pts (WorkBuddy-Bench), +4.5 (JobBench), +11.8 puntos porcentuales de partial pass rate en LAB. Más `--k` (presupuesto de recursión) sigue mejorando. Benchmarks: JobBench / LAB / WorkBuddy-Bench — trabajo profesional, legal, office. Executors: OpenCode y Codex.

**Qué aplicaría a Hipotenusa.** Los ocho componentes son, literalmente, la superficie de este repo: SOUL/prompts, `skills/`, `plugins/`, `VoiceMemoryLedger`, las tools `create_skill` / `update_skill` / `create_workflow` / `update_soul`, `WorkflowEngine` y los subagentes. O sea, el *patrón* cae sobre algo que ya existe. Lo que **no** cae: los benchmarks (legal/office, nada de voz) y el requisito de modelos con credenciales — las corridas model-backed piden Vertex AI + `gcloud auth`, Node 20 y Docker para WorkBuddy. `harness2-demo` corre gratis y sin credenciales, pero corre *sus* benchmarks, no los de Hipotenusa.

**Coste.** Patrón mínimo, con el router local en vez de Vertex: **6–8 h**. Un archivo `improvement-harness.md` por depto (harness adoptado + lecciones con evidencia), y un probe que re-corre la misma tarea de voz con dos variantes de skill editada y compara por contrastes — sin tocar plugins. Correr el framework tal cual: imposible sin presupuesto de API y sin un task suite propio.

**Riesgo.** Medio. Es auto-modificación de prompts/skills: sin set congelado, un "mejor" auto-reportado puede ser deriva. Mitigante que ya existe: `SoulSnapshotStore` (rollback) + el set de eval de E1 (§Veredicto). Y el costo es de créditos si alguien prende Vertex por error: dejarlo explícito en el README del experimento.


## Veredicto

| | Qué | Por qué |
|---|---|---|
| **Implementaría hoy** | Consolidación **textual** offline: JSONL del día → candidatos declarativos → `VoiceMemoryLedger.refine()`, corriendo en **Hipotenusa** (noche, celu quieto) y, con otro insumo, en **Korat** (al cerrar cada corrida → priors en el OKF). Antes que nada, el set de eval derivado de los logs. | Único pedazo de estos papers que entra sin entrenar nada. Reversible (snapshot/rollback). No toca `eot_gate` ni `turn_gate`. |
| **Adoptaría como patrón (Harness²)** | `improvement-harness.md` por depto + probe Propose–Probe–Compose con el router local. | Los ocho componentes de Harness² ya existen acá (SOUL, skills, plugins, ledger, tools de edición). El framework tal cual no: benchmarks legal/office y Vertex AI, sin presupuesto. |
| **No implementaría** | Expansión MoE + knowledge seeding + dreaming (2606.03979); fast weights en `W_down` (2604.06169); pasadas recurrentes sobre bloques SSM (2605.26099). | Los tres piden entrenamiento y/o cambio arquitectónico. Esta máquina entrena como mucho un adapter chico, y ningún modelo servido expone los pesos que esos métodos necesitan. |
| **Falta medir** | (a) ¿la consolidación nocturna mejora algo en la sesión siguiente? No hay benchmark. (b) ¿cuántos facts/día propone el LFM3 local y cuántos sobreviven la regla de higiene? (c) ¿en cuántos días satura el tope de 200 entradas? (d) ¿el set de EOT derivado de `closed_by` coincide con las etiquetas del gate? (e) ¿un refresh LoRA nocturno degrada a 2B? — **no publicado**. | Son cinco huecos de evidencia, no cinco features. |

## Orden de experimentos (chicos, en este orden)

**E1 — Logs → set de eval de EOT. 3 h. Cero riesgo.**
`scripts/qa/build_eot_eval.py` (nuevo) lee `logs/session-*.jsonl`, arma pares (texto del turno, etiqueta) usando `closed_by`: `next_transcription`/`interrupt` = el usuario siguió hablando; `voice_idle` = terminó. Salida `out/eot-eval-YYYY-MM.jsonl`.
*Criterio de aceptación:* ≥200 turnos etiquetados, y re-correr `eot_gate` sobre ellos. Si el F1 cae fuera de ±0.05 de 0.841/0.645, el gate fue calibrado sobre otra distribución — dato que hoy no tienen y que vale más que cualquier paper.

**E2 — Consolidación nocturna en dry-run. 4–6 h. Cero escrituras.**
Mismo script + timer 03:00 (Hipotenusa: perfil phone, corre con el celu quieto; no en el turno) leyendo las últimas 24 h, prompt al llama-server `:11434` pidiendo sólo `facts` / `relationships` / `action_patterns`, dedupe contra `memory/{dept}.json`, e imprime candidatos sin escribir.
*Criterio de aceptación:* ≥5 candidatos por noche y ≥80 % pasando revisión manual de higiene. Si no llega a 5, la idea muere acá por 4 horas, no por dos semanas.
*Si pasa:* activar escritura con tope de N=5/noche y `evidence` obligatoria; medir tokens añadidos al prompt y saturación del ledger.

**E3 — Sólo si E2 satura el ledger: refresh LoRA con guardrail de plasticidad. 2–3 días.**
Fine-tune de LFM3-LoRA sobre los intercambios del día, eval congelado antes/después (paper 2 como regla, no como método), tope de refreshes, adaptador anterior preservado para rollback.
*Criterio de aceptación:* ninguna regresión en el set congelado; si hay regresión, se queda la memoria textual y se archiva el refresh.

Regla que sale de todo esto: **estos papers son de cómputo offline, de consolidación y de edición del harness; ninguno toca clasificadores de turno.** `eot_gate` sigue donde está, y el destino de lo que se adopta es la memoria de Hipotenusa y los priors de Korat. Lo que se adopta es el *horario* (correr fuera del turno) y el *bucle* (proponer, probar, componer), no el mecanismo.
