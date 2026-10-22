# MASK-R1 — ¿Existe un solo modelo que haga VAD → ASR rioplatense → clasificación → TTS con barge-in?

**Fecha:** 2026-10-20 · **Tarjeta:** t_mask_r1 · **Alcance:** local only, sin API.
**Estado:** investigación cerrada. Cada número de acá salió de un comando en esta máquina o del
model card citado. Lo que no pude verificar está marcado **NO VERIFICADO**.

---

## 0. Veredicto

**No existe hoy un modelo abierto que haga las cuatro cosas en español rioplatense y entre en este
hardware.** El único que hace audio-in y audio-out en español es Qwen3-Omni-30B-A3B y necesita ~20 GB;
acá hay 4 GB de VRAM y 8 GB de RAM libres. Los omni que sí entran (LFM2.5-Audio-1.5B, Moshi 7B,
MiniCPM-o 4.5, Nemotron VoiceChat 11B) son **inglés** (o chino/inglés) en voz.

Y hay un dato que cambia el eje del pedido: **el "modelo único" no te compra latencia, te compra
barge-in**. La latencia ya la tenés cascada (abajo: 1,95 s para 32,7 s de audio, RTF 0,06 en CPU).
Lo que la cascada no tiene es la decisión de turno — y eso no requiere un omni: requiere una cabeza
de 14 M de parámetros (patrón Tyger) sobre features que ya estás calculando.

Recomendación en una línea: **cascada + cabeza de turno/barge-in propia (Tyger-style) + ASR por
WER medido + Piper es_AR como TTS de streaming**. Detalle y plan en §5 y §6.

---

## 1. Qué se midió en esta máquina (no es vendor claim)

Hardware real: RX 6500 XT **4 GB** (Vulkan + ROCm, gfx1034), Intel DG1, **31 GB RAM con 23 en uso**,
`/run/media/chaos/terciario` con **105 GB libres**.

Servicios vivos ahora (verificado con `ss -ltnp`):

| Puerto | Qué | Proceso |
|---|---|---|
| 8098 | ASR OpenAI-compatible | `crispasr`, backend `parakeet`, modelo `parakeet-ultra-q8_0.gguf` (674 MB) |
| 8091 | clasificador de intención | python (Kateto) |
| 8092 | LLM de voz | `llama-server` |
| 11434 | router LLM local | `llama-server` |
| 8095/8096/8097/8099 | otros sidecars (no relevados) | — |

**Medición de hoy, sobre la misma muestra rioplatense del benchmark de septiembre**
(`asr-benchmark/audio/prueba_asr.wav`, 32,71 s, 55 palabras de ground truth):

| Qué | Valor |
|---|---|
| Modelo servido | `parakeet-ultra-q8_0.gguf`, crispasr, `language=es` |
| Wall (HTTP, server caliente) | **1,95 s** → **RTF 0,060** |
| WER normalizado (DP, sin puntuación) | **29,09 %** (ref 55 / hyp 48) |
| Errores típicos | "Gabriel"→"Ariel", "OS"→"OSU", números en dígitos |

Benchmark de septiembre (misma muestra, `asr-benchmark/REPORT.md`), para comparar motor contra motor:

| Motor | WER | RTF | RAM peak |
|---|---|---|---|
| qwen3-asr **1.7B** Q8 | **10,91 %** | 1,046 | 3,9 GB |
| nemotron-3.5-asr-streaming 0.6B | 21,82 % | 0,174 | 1,5 GB |
| qwen3-asr 0.6B | 25,45 % | 0,304 | 2,6 GB |
| **parakeet-tdt-0.6b-v3 Q8** | 27,27 % | 0,125 | 1,3 GB |
| whisper-large-v3-turbo (q8) | 34,55 % | 0,259 | 0,15 GB |

Lectura honesta: **parakeet es el más rápido y el segundo peor en WER sobre acento rioplatense.**
qwen3-asr-1.7B es 3× mejor en WER y 17× más lento (RTF > 1 significa *no* es tiempo real en esa
medición, que corrió con descarga parcial del modelo: **NO VERIFICADO** que ese RTF se sostenga con
el modelo completo en RAM caliente).

Nota sobre nemotron: transcribió espanglish/chino en un fragmento ("好了, 是有点") — no lo descartaría
por eso, pero sí lo miro dos veces antes de usarlo como ASR de producto.

---

## 2. Correcciones de premisa (antes de escribir el brief de MASK-3)

Tres cosas de la tarjeta no son como están escritas. Corregirlas ahora cuesta cero; descubrirlas en
MASK-3 cuesta una corrida entera.

**2.1 Tyger no es un "clasificador de 2 etapas".** Es un modelo de decisión de turno
(`nineninesix/tyger`, 652 M = Nemotron 3.5 ASR Streaming 0.6B congelado + GRU causal de 14 M,
3 capas × 768, FP32 2,61 GB). Entra **dos streams alineados de 16 kHz** (mic del usuario + playback
del agente), saca una frame cada 320 ms y por frame emite: estado de turno
(`listen|hold|speak|backchannel`), y scores de *hazard*, barge-in, backchannel y endpoint. 9 KiB de
estado por conversación. Entrenado desde cero sobre Open Yap 1K (1.395 conversaciones) con etiquetas
automáticas de quién habla cuándo. **Idioma: inglés.**

O sea: no clasifica intención ni herramientas. Resuelve *cuándo hablo, cuándo escucho, cuándo me
interrumpen y cuándo un "mm-hm" no es interrupción*. Eso es exactamente lo que la VAD de silencio no
puede distinguir (una pausa para pensar y un pedido de turno duran lo mismo).

**2.2 El "Parakeet Redux" que corre en esta máquina no es el 1.58-bit.** En
`/run/media/chaos/secundario/proyectos/redux-gguf/models/` hay dos GGUF de **674 MB**
(`parakeet-redux-q8_0.gguf`, `parakeet-ultra-q8_0.gguf`, md5 distintos). El release 1.58-bit real
(`moondream/parakeet-redux`) pesa **178–207 MB** y corre matmuls enteros con el runtime **Photon**;
no es un GGUF y no lo sirve crispasr. Los 674 MB son Q8 de la familia 0.6b-v3.

Consecuencia para MASK-3: la ventaja "mobile/CPU, 113× realtime, 178 MB" **no la estás usando**;
estás usando un Q8 de 674 MB en un server local. Está bien — el teléfono sólo manda PCM, el modelo
corre en la PC — pero no escribas el plan como si fuera el packed de 1.58-bit.

**2.3 `parakeet-tdt-0.6b-v3` no auto-detecta idioma en nuestro stack.** El model card de NVIDIA dice
auto-detección sobre 25 idiomas; `transcribe.cpp` documenta **"no auto-detect — language hint
required"**. Kateto ya lo tiene bien (`language = "es"` en `[plugin.audio_processor_parakeet]`). Si
alguien "limpia" esa línea, el WER se va a las nubes y va a parecer un problema de acento.

---

## 3. Comparación por rol

### 3.1 ASR (español, acento rioplatense)

| Candidato | Tamaño / runtime | Español | Veredicto |
|---|---|---|---|
| **parakeet-tdt-0.6b-v3** (Q8, crispasr) | 674 MB, CPU/GPU | 25 idiomas, es ok | **el que corre**; RTF 0,06 pero 29 % WER acá |
| parakeet-redux 1.58-bit (moondream) | 178–207 MB, runtime Photon | hereda los 25 | interesante, **no sirve con crispasr**; sumaría un runtime nuevo |
| **qwen3-asr-1.7B** | 2,5 GB Q8, CPU | es | mejor WER medido (10,9 %); RTF ~1 → sólo si se acelera |
| nemotron-3.5-asr-streaming 0.6B | 752 MB | es | 21,8 % WER, streaming nativo; ojo alucinaciones zh |
| Whisper large-v3-turbo | 0,5–0,9 GB | es | peor WER acá; sólo como fallback |
| HiTZ whisper-large-v3-es | ~3 GB | es (CV13) | 4,93 % WER en lectura; **NO VERIFICADO** en rioplatense |
| **Whistle** (Cactus) | **16,9 MB**, CPU puro | es (una de 7) | 11 ms TTFT, timestamps por palabra, embedding de habla, Apache-2.0 — pero FLEURS avg **21,4 % WER**: es un modelo de dictado corto, no de conversación. Sirve como **detector de habla/semántico barato**, no como ASR principal |

### 3.2 Decisión de turno / barge-in (la pieza que falta)

| Candidato | Qué da | Idioma | Veredicto |
|---|---|---|---|
| Silero VAD (ya en uso) | habla/no habla, 10–30 ms | agnóstico | necesario, insuficiente: no distingue pausa de fin de turno |
| **Tyger** | estado de turno + hazard + barge-in + backchannel | **inglés** | la **arquitectura** es la respuesta, los pesos no |
| SoulX-Duplug 0.6B | semantic VAD + ASR streaming, 240 ms | zh/en | misma conclusión |
| gate semántico de Kateto (`audio_input/base.py`) | interrupt semántico propio, ya implementado | es | el caballo de batalla actual; es el lugar donde enchufar la cabeza entrenada |

### 3.3 Clasificación (2 etapas, como hay que leerla)

1. **Etapa acústica (~10 ms, por frame):** ¿hay habla? ¿está dirigida a mí? ¿es backchannel? → cabeza
   de turno (§3.2). No necesita texto.
2. **Etapa semántica (por turno, post-ASR):** intención + herramienta → ya existe:
   `[plugin.executor_classifier]` en **:8091** y `[plugin.executor_workflow_router]` (hoy
   `enabled = false`).

No hay nada que comprar acá. Lo que hay que hacer es que la etapa 1 exista y sea medible.

### 3.4 TTS en streaming

| Candidato | Español | Streaming | Costo local | Veredicto |
|---|---|---|---|---|
| **Piper `es_AR-daniela-high`** (instalado en `~/.local/share/piper/voices/`) | rioplatense real, s aspirada | por frase (chunking propio) | CPU, ~0 VRAM | **default del mask** |
| Zonos :8093 (config `enabled = true`, `stream = true`) | multilingüe, clonación zero-shot | sí | GPU/CPU | mejor timbre, más pesado; hoy no está escuchando |
| **Qwen3-TTS 0.6B / 1.7B** (Apache-2.0, ene-2026) | 10 idiomas **incluye es**, perfiles dialectales | **97 ms primer paquete**, clonación con 3 s | ~2,7 GB VRAM idle (0.6B) | el experimento que vale: clone + streaming; **NO VERIFICADO** si hay camino GGUF/CPU |
| NeuTTS nano es (hay muestra en `kateto-tts/neutts-nano-es.wav`) | sí | ? | CPU | ya probado, sin números |

### 3.5 El "modelo único" (audio in + audio out + razonamiento)

| Modelo | Params | Español **voz** | Entra acá | Nota |
|---|---|---|---|---|
| **Qwen3-Omni-30B-A3B** | 30B MoE / 3B act. | **sí, in y out** (19 in / 10 out, es en ambas) | **no** (~18–20 GB Q4 vs 4 GB VRAM) | half-duplex nativo; hay retrofit full-duplex (DuplexOmni). Es el objetivo si algún día hay 24 GB |
| MiniCPM-o 4.5 | 9B | **no**: voz en zh/en (CosyVoice2/Whisper) | no (int4 ~11 GB) | full-duplex real, Apache-2.0; gran arquitectura, idioma equivocado |
| NemotronLabs VoiceChat 11B | 11B | **no**: en only | no (80 GB oficial) | full-duplex + tool calling, licencia **research-only** |
| LFM2.5-Audio-1.5B | 1,5B | **no**: model card dice "Supported languages: English" | sí (GGUF llama.cpp, CPU) | end-to-end audio→audio, licencia LFM Open (no Apache) |
| Moshi / moshiko 7B | 7B | no (en) | no | ~200 ms primer audio, Apache-2.0 |
| Qwen3.5-Omni | ~30B/3B | 36 idiomas de salida (**NO VERIFICADO**) | no | misma barrera de memoria |

### 3.6 Bases 8B–24B con adapter/LoRA (lo que pidió la tarjeta)

| Base | Qué es en realidad | Audio | Veredicto |
|---|---|---|---|
| **Orion-26B-A4B-v1** (TheDrummer) | fine-tune de **Gemma 4 26B-A4B** | no (el 26B-A4B no lleva audio en Gemma 4) | sirve para persona/tools, no para voz |
| **Gemma 4 E2B / E4B** | 2,3B/4,5B efectivos, **audio de entrada**, Apache-2.0 | in sí, out no | no reemplaza al ASR (encoder es de comprensión, CoVoST, no de transcripción), y no habla |
| **LFM2-8B-A1B** | MoE texto 8B/1B activo | no (el audio es LFM2-Audio, otro modelo de 1,5B) | texto/tools |
| **Qwen3.6-12B** | **no existe como base oficial**: lo que hay son merges "hermanados" de un 27B recortado a 12B (DavidAU) | no | base dañada por el recorte; no es candidato para nada nuevo |
| **Cyberdonia-24B-v8** | fine-tune de texto 24B (familia Mistral Small) | no | texto/rol |
| Mistral-Nemo-12B | 12B denso, 128k | no | texto/tools; el más honesto de la lista para LoRA |

**La conclusión de §3.6 es la de siempre y conviene decirla sin vueltas: un adapter/LoRA te da la
persona y las herramientas del LLM. No te da audio ni entrada ni salida.** Para tener voz hay que
elegir una base que ya tenga encoder/decoder de audio, y ninguna de 8–24B lo tiene en español.

---

## 4. Por qué la cascada no es el problema (y qué sí lo es)

Lo que ya está resuelto en Kateto, verificado leyendo el código y el config:

- `audio_input_mask` con Silero VAD, `interrupt_on_vad`, `turn_silence_timeout` y — esto es lo
  importante — un **gate semántico de interrupción** (`semantic interrupt gate`) más discriminador de
  nivel y `barge_in_min_speech_ms` para que el parlante del celular pegado al micrófono no se
  auto-interrumpa (comentarios en `config/defaults/config.toml:200-206`).
- ASR por HTTP, clasificador por HTTP, LLM de voz por HTTP, TTS por HTTP. Todo reemplazable por
  config, sin tocar código.
- TTS con proveedor Piper por voz (`ts` en `test_piper_tts.py`), voz `es_AR-daniela-high` instalada.

Lo que no está: **la etapa 1 de §3.3 medida como tal**. Hoy el barge-in es un umbral de energía +
silencio + un gate semántico sobre texto parcial. Eso funciona con el dueño hablándole a un celular
en una habitación quieta y falla en cuanto hay TV, ventilador o alguien más hablando. Tyger existe
exactamente porque ese umbral no alcanza.

---

## 5. Recomendación

1. **ASR: no cambiar por moda, cambiar por número.** Correr el mismo set rioplatense contra
   `parakeet-ultra-q8` (29,1 % hoy), `qwen3-asr-1.7B` (10,9 %) y `nemotron-streaming` (21,8 %) con el
   modelo completo y caliente, y elegir con la tabla en la mano. Regla de corte propuesta:
   **RTF ≤ 0,25 y WER ≤ 15 % en CPU**. Si nadie cumple, parakeet se queda y el WER se ataca con
   **post-proceso** (normalizador de números + léxico rioplatense: "OSU"→"OS", "Ariel"→"Gabriel" sólo
   si el contexto lo pide) antes que con otro modelo.
2. **Turno/barge-in: cabeza propia de 14 M estilo Tyger.** No entrenar el ASR; entrenar sólo la
   cabeza. Entradas: features de 80 ms (mel + embedding del encoder de parakeet si crispasr los
   expone — **NO VERIFICADO**, y si no los expone se arranca con mel+VAD+texto parcial). Salidas por
   frame: `listen|hold|speak|backchannel` + score de barge-in. Datos: los `conversation_log` JSONL
   que ya se escriben + 200 solapamientos etiquetados a mano. Costo: horas de CPU, no GPU.
3. **TTS: Piper `es_AR-daniela-high` como camino caliente del mask** (CPU, determinista, no compite
   por VRAM con el LLM). Zonos queda para clonación cuando la GPU está libre. Qwen3-TTS 0.6B es el
   único experimento que puede sacarle el puesto a los dos, por 97 ms de primer paquete y clonación
   con 3 s — pero primero hay que ver si corre sin GPU.
4. **Modelo único: no ahora.** Qwen3-Omni-30B-A3B es el único con voz en español y pide ~20 GB.
   Criterio de disparo: cuando haya una GPU de 24 GB, se evalúa contra el fixture de §6-F0 con la
   misma vara. Antes de eso es gastar una semana para aprender lo que ya dice esta tabla.

---

## 6. Plan de prototipo

Cada fase deja un artefacto en ruta absoluta y un gate que se corre con un comando. Nada de "quedó
andando" sin número.

**F0 — fixture de medición (0,5 día).**
Artefacto: `/run/media/chaos/terciario/proyectos/mask-asr-eval/` con 20 clips rioplatenses (mic de
celular, 16 kHz, con y sin ruido de fondo), `ground_truth.jsonl`, y `eval.py` que reporta
WER/CER/RTF/p50-p95 por motor.
Gate: `python3 eval.py --engines parakeet,qwen3-asr-1.7b,nemotron` imprime tabla y devuelve
`exit 0` sólo si midió los 3. Reproducible con un comando.

**F1 — elegir ASR con números (1 día).**
Artefacto: `mask-asr-eval/report.md` con la tabla completa y la elección.
Gate: RTF ≤ 0,25 **y** WER ≤ 15 % en CPU, medido en F1, no copiado.

**F2 — cabeza de turno v0 (2 días).**
Artefacto: `mask-turnhead/` con `train.py`, `head.pt` (≤ 20 M params), `eval_turnhead.py`.
Etiquetas: ventanas de 320 ms con `{listen, hold, speak, backchannel}` + barge-in binario.
Gate: en 30 casos held-out, **precision y recall de barge-in ≥ 0,90** y latencia de decisión
**< 400 ms**; false-barge-in (cortar por un "mm-hm") ≤ 1/30.

**F3 — TTS + flush de barge-in (1 día).**
Artefacto: `mask-asr-eval/tts-latency.md`.
Gate: **time-to-first-audio < 300 ms** con Piper; **stop < 150 ms** desde que la cabeza dice
barge-in, medido con el parlante del celular al lado del micrófono (el caso real, sin AEC).

**F4 — referencia "modelo único" (1 semana, sólo con ≥ 24 GB).**
Qwen3-Omni-30B-A3B contra el fixture de F0, misma vara. Sirve para saber qué se ganaría antes de
mudar la arquitectura.

Lo que **no** entra en el plan: reentrenar el ASR, montar el runtime Photon para el 1.58-bit, o
migrar a un omni. Ninguna de las tres paga su costo con los números de §1.

---

## 7. Riesgos

- **Sin AEC y el parlante pegado al micrófono.** Es el caso físico — no hay dongle. La cabeza de turno
  tiene que entrenarse **con el playback del agente como segunda entrada** (Tyger hace exactamente
  eso). Si se entrena sólo con el mic, va a aprender a interrumpirse a sí misma.
- **crispasr no es streaming.** Ventanas de 8 s re-codificadas por hop, como Tyger hace con Nemotron.
  Si crispasr no expone features internas, la cabeza arranca sobre mel — más débil, pero medible.
- **qwen3-asr-1.7B con RTF > 1** en el benchmark de septiembre. Antes de descartarlo hay que repetir
  la medición con el modelo completo (la nota del propio REPORT dice "descarga 34-40 %, placeholder").
- **La fila "Nemotron 21,8 %" con chino adentro.** Un motor que alucina otro idioma en silencio es
  peor que uno con más WER, porque rompe el clasificador aguas abajo.
- **VRAM compartida.** 4 GB y el LLM de voz ya usa :8092 y :8097. Cualquier cosa nueva que pida GPU
  compite; el TTS del mask tiene que ser CPU o nada.

---

## 8. Estado de Kateto-train: qué faltaba para cerrarlo

Relevado en `/run/media/chaos/terciario/proyectos/kateto-train` (git al 2026-10-17, último commit
`8eee078 fix(kaggle): inicializar el submodulo RWKV-PEFT antes de entrenar`).

**Lo que sí está producido:**

| Artefacto | Tamaño / fecha |
|---|---|
| `out/kateto-rwkv29-merged.pth` (2.9B fusionado) | 8,7 GB · 2026-09-05 |
| `out/kateto-rwkv29-f16.gguf` / `-Q4_K_M.gguf` | 5,6 GB / 1,8 GB · 2026-09-05 |
| `out/quants/kateto29-Q6_K.gguf` / `-Q8_0.gguf` | 2,6 / 3,3 GB · 2026-09-12 |
| estados de voz `out/rwkv_states/{jane,seco-…,streamer,whisperer}/` | 6,3 MB cada uno · 2026-09-06 |
| base oficial `base/rwkv7-g1j-2.9b-…pth` | 5,9 GB |

**Lo que falta, y es lo que bloquea el cierre:**

1. **El 1.5B no existe.** Los dos checkpoints subidos desde Kaggle están en **0 bytes**:
   `/run/media/chaos/secundario/kateto-kaggle-out/kateto-ckpt/kateto-1.5b-v2.pth` (27-sep) y
   `kateto-1.5b-seco.pth` (08-oct). Un `ls -la` alcanza para verlo. O sea: la cadena se cortó en la
   subida, no en el entrenamiento.
2. **El entrenamiento local no pasa de la época 1.** `out/entrenar-local-1.5b.log`:
   `torch.OutOfMemoryError: HIP out of memory … total capacity of 3.98 GiB` en el `cross_entropy`;
   `out/entrenar-orpo-1.5b.log`: mismo OOM en `_logp_medio` del paso ORPO. Coincide con el handoff
   del 15-oct: la época 1 cierra sana y la 2 muere al arrancar.
3. **El hilo abierto es un NaN en ORPO.** `kaggle_orpo/kateto_orpo_v7_2xt4.ipynb` (18-oct) existe para
   eso: corre sobre `kateto-v7-sft` (`rwkv-0.pth`, 3.055.569.567 bytes chequeados a mano) con
   instrumentación `[orpo-diag]` por paso (`tot_finite`, `lw_finite`), corrida B en fp32 si A da NaN,
   y un veredicto automático de tres estados ("LIMPIO EN BF16" / "BF16 NA el NaN, FP32 LIMPIO" / "NaN").
   **No pude verificar si esa corrida se ejecutó ni su veredicto**: no hay log de ese kernel en disco
   y no hay commit posterior al 17-oct.
4. **La vara de evaluación sigue siendo el hueco de fondo** — lo dice el propio handoff del 15-oct:
   `eval_v2` da 0 silencios sobre 30 con un modelo que emite papilla fluida. Sin held-out de contenido
   verificable, "terminado" no significa nada aunque el checkpoint exista.

**Resumen en una frase:** a Kateto-train no le faltan datos ni arquitectura; le falta **una corrida de
ORPO que no muera en NaN ni en OOM y una subida que no llegue en 0 bytes**, más una vara que distinga
registro de conocimiento. Las tres cosas están identificadas y dos de las tres ya tienen el
instrumento escrito.

---

## 9. Fuentes

- parakeet-tdt-0.6b-v3 (25 idiomas, puntuación/mayúsculas): https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- transcribe.cpp: contrato del runtime, "no auto-detect", limitaciones: https://github.com/handy-computer/transcribe.cpp/blob/main/docs/models/parakeet.md
- parakeet-redux 1.58-bit (178–207 MB, runtime Photon, tabla FLEURS): https://huggingface.co/moondream/parakeet-redux
- Whistle (16,9 MB, 7 idiomas, Apache-2.0, timestamps + embedding): https://huggingface.co/Cactus-Compute/whistle
- Tyger (652 M, GRU de turno, salidas y dataset): https://huggingface.co/nineninesix/tyger
- SoulX-Duplug 0.6B (semantic VAD, 240 ms): https://github.com/Soul-AILab/SoulX-Duplug
- LFM2.5-Audio-1.5B (end-to-end audio, **English only**, LFM Open License): https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B
- MiniCPM-o 4.5 (9B full-duplex, Apache-2.0, int4 ~11 GB, voz zh/en): https://arxiv.org/html/2604.27393
- NemotronLabs VoiceChat 11B (**en only**, 80 GB, research-only): https://huggingface.co/nvidia/NVIDIA-NemotronLabs-VoiceChat-11B
- Qwen3-Omni (es en entrada y salida de voz): https://github.com/QwenLM/Qwen3-Omni
- Qwen3-TTS (Apache-2.0, 97 ms, 10 idiomas, clonación 3 s): https://github.com/QwenLM/Qwen3-TTS
- Gemma 4 (E2B/E4B con audio de entrada; 26B-A4B sin audio): https://huggingface.co/blog/gemma4
- Piper voces es_AR: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md
- Medición local de ASR: `/run/media/chaos/terciario/proyectos/asr-benchmark/REPORT.md` +
  corrida propia del 2026-10-20 contra `:8098` (tabla en §1).
