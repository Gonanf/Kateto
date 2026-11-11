---
title: "Evaluación: MiniCPM-o 4.5, SoulX-Duplug, TurnSense y VoXtream"
description: "Qué corre en esta máquina, qué no y por qué; qué concepto se adopta sin el modelo."
---

# Cuatro piezas candidatas para el stack de voz

Evaluación de nov-2026 contra el hardware real, no contra el ideal. Lo que ya corre:
**LFM3-Omni-2B en duplex por `/v1/realtime` sobre llama.cpp master, ~300 ms al primer audio**.
Ese es el baseline: cualquier pieza nueva tiene que vencerlo o resolver algo que él no hace.

## Hardware de referencia

| Componente | Realidad |
|---|---|
| GPU | RX 6500 XT, 4 GB, `gfx1034` (Navi 24). **No está en la lista oficial de ROCm**; se fuerza con `HSA_OVERRIDE_GFX_VERSION=10.3.0`, sin garantía y con kernels faltantes. |
| GPU 2 | Intel Iris Xe DG1, Vulkan, ~3.6 GB libres. Sirve para llama.cpp Vulkan; no para stacks CUDA/PyTorch. |
| CPU | i3-10105F, 4c/8t. |
| RAM | 31 GB. |

Regla que sale de esto: **todo lo que exija CUDA queda fuera**, y todo lo que exija más de ~3 GB de VRAM también. Lo único que entra sin trucos es CPU (llama.cpp/ONNX) o Vulkan.

## Veredicto rápido

| Pieza | Qué es | Corre acá | Veredicto |
|---|---|---|---|
| [MiniCPM-o 4.5](https://huggingface.co/openbmb/MiniCPM-o-4_5) | Omni 9B end-to-end, audio+visión in, audio out, full-duplex | **No** | **No se adopta el modelo.** Se adopta la idea de sincronización por timeline. |
| [SoulX-Duplug-0.6B](https://huggingface.co/Soul-AILab/SoulX-Duplug-0.6B) | Predictor de estado de turno, streaming, plug-and-play | **No tal como viene** | **No se adopta el modelo.** Se adopta la máquina de estados `idle / nonidle / speak`. |
| [TurnSense](https://github.com/Bairong-Xdynamics/TurnSense) | Detector semántico de fin de turno, 3 clases, 47M | **Sí** (ONNX CPU) | **Se adopta el concepto y se prueba el modelo**, con la salvedad de idioma. |
| [VoXtream](https://github.com/herimor/voxtream) | TTS zero-shot full-stream, 0.5B, GGUF/llama.cpp | **Sí** (CPU, GGUF int8) | **Se adopta como piloto de TTS**, no como default todavía. |

---

## 1. MiniCPM-o 4.5 — no entra, y además habla chino/inglés

**Qué es.** Modelo omni end-to-end de 9B construido sobre SigLip2 + Whisper-medium + CosyVoice2 + Qwen3-8B. Full-duplex real: entrada de video/audio continuo y salida de texto+audio concurrentes, con multiplexado por franjas de tiempo (TDM) y decisión proactiva de hablar a 1 Hz. Licencia **Apache-2.0** (pesos y código, según el card).

**Qué pide.** El card declara, para inferencia PyTorch, **19 GB de VRAM en bf16 y 11 GB en int4**, y recomienda 28 GB de GPU para el demo web. El camino end-side (`llama.cpp-omni`, fork de OpenBMB) declara: full-duplex omni con **≥12 GB de VRAM** (o Apple M4 Max con 24 GB de RAM unificada); half-duplex con ≥12 GB (o M3/M4/M5 con 16 GB). Los GGUF del fork, medidos por sus propios números: **Q4_K_M ~8 GB de pesos, ~9 GB de VRAM**; Q8_0 ~11/~13 GB; F16 ~18/~20 GB. El piso real es 9 GB — más del doble de lo que hay.

**No corre en llama.cpp vanilla.** El full-duplex vive en [`llama.cpp-omni`](https://github.com/OpenBMB/llama.cpp-omni), no en `ggml-org/llama.cpp`: es un motor aparte que parte el modelo en cinco GGUF (VPM, APM, LLM, TTS, Token2Wav) y expone `/v1/stream/omni_init`, `/v1/stream/prefill`, `/v1/stream/decode` con SSE propio (`content`, `is_listen`, `stop`) y WAVs en disco. El build detecta **CUDA o Metal** en CMake; **Vulkan/ROCm no están documentados**. O sea: ni la RX 6500 XT ni la DG1 lo aceleran, y el CPU-only del fork con 31 GB de RAM no tiene latencia publicada (`no publicado`).

**Latencia publicada.** TTFT (primer audio) **<550 ms en RTX 4090 F16** y **<650 ms en M4 Max**, del README del fork. No hay número para CPU ni para GPUs chicas.

**El idioma es la razón decisiva.** El ASR es Whisper-medium y el TTS CosyVoice2: conversación **zh/en**. Las voces de Hipotenusa (Jane, Doktor, Conquest) son español rioplatense; aunque entrara en 4 GB, no las podría decir. Ajustar idioma = reentrenar un omni de 9B; no es una decisión de despliegue.

**Qué queda.** El diseño, no los pesos: alinear los streams de entrada y salida sobre una línea de tiempo en milisegundos (TDM) y decidir "hablo / no hablo" a frecuencia fija en vez de esperar un evento. Hipotenusa ya tiene la mitad: sesión duplex por `/v1/realtime` con LFM3-Omni-2B y gate de turno. Nota de integración: `hipotenusa/plugins/audio_processor/omnimodal_connector.py` espera eventos tipo `response.audio.delta` de la Realtime API; el README de llama.cpp-omni documenta `/v1/stream/*`, **no** `/v1/realtime`. Hoy ese puente no existe (ver bug 57, forma de frame).

---

## 2. SoulX-Duplug-0.6B — el peso entra, el stack no

**Qué es.** VAD semántico plug-and-play: predice el estado del diálogo por chunks de audio, guiado por texto. Salida por chunk: `idle` (silencio/ruido/backchannel), `nonidle` (hay contenido semántico, sigue el turno), `speak` (el usuario terminó y la frase está semánticamente completa), `blank` (chunk incompleto, cacheado). Trae `max_wait_num` como red de seguridad para falsos `incomplete` y `far_field_threshold` para audio lejano. Por debajo: Qwen3-0.6B con vocabulario expandido, tokenizer de GLM-4-Voice y LoRA r=32. Licencia **Apache-2.0**.

**Qué pide.** `config.yaml` fija `device: cuda`, `precision: bf16`, y engancha un ASR aparte (`paraformer` para chino, `sensevoice` para inglés/bilingüe) vía FunASR. Los `requirements.txt` están clavados a CUDA: `onnxruntime-gpu`, `cupy-cuda12x`, `tensorrt-cu12`, `vllm`, `bitsandbytes`, `xformers`, wheels `nvidia-*`. El modelo en sí (0.6B bf16 ≈ 1,2 GB) **entraría** en 4 GB; lo que no entra es el servidor. Portarlo a ROCm/Vulkan implica reescribir su runtime y su ASR, no cambiar una flag.

**Latencia.** El card **no publica** latencia. El doc interno `docs/MASK-R1-modelo-integrado-2026-10-20.md` cita 240 ms, sin fuente verificable en el card → tratarlo como `no verificado`. El demo online está caído desde 2026-07-17 según el README.

**Idioma.** El camino práctico es zh/en: SenseVoice cubre zh/yue/en/ja/ko, no español. Para rioplatense habría que cambiar el ASR y probablemente reentrenar la cabeza.

**Qué queda, y es lo valioso.** La **máquina de estados** como etapa explícita entre ASR y LLM: `nonidle` mantiene el turno abierto sin esperar silencio (una pausa para pensar y un fin de turno duran lo mismo para un VAD de energía), `speak` recién cuando la semántica cierra, `idle` ignora backchannels. Hipotenusa ya tiene la versión textual en `eot_gate.py` (`RESPOND / WAIT / SUPPRESS`, fail-open sobre las 2 etapas de `clasificador_hibrido.py`). Un port de DuplexCascade (`turn_policy.py`, micro-turnos `wait / respond / backchannel` por reglas) se escribió y se descartó: duplicaba las mismas dos etapas. Lo que falta en `eot_gate` es la etapa acústica: decide sólo sobre texto, así que sigue colgado del ASR. Duplug aporta justamente eso — decisión antes de que haya texto — y de yapa `max_wait_num` como fallback (bug 135) y un filtro de audio lejano análogo al `speaker != owner → WAIT` que ya existe.

---

## 3. TurnSense — 47M que sí corren, en un idioma que no es el nuestro

**Qué es.** Clasificador semántico de turno en **tres clases**: `complete` (podés responder), `incomplete` (sigue hablando), `invalid` (ruido/risa/muletilla: no responder). 47M de parámetros, FP32 e **INT8 ONNX (~50 MB)**, entrada audio + texto ASR. Licencia Apache-2.0 (el `LICENSE` del repo es Apache-2.0 pelado; el README dice "con restricciones adicionales" — inconsistencia a revisar antes de empacar).

**Números del repo.** `easyturn_real_test_ZH` (300 muestras): F1 `complete` **96,35%**, F1 `incomplete` **96,32%**, **p50 54,65 ms / p90 58,00 ms** (hardware no declarado). `semantic_test_ZH` (2000): 92,30 / 91,62. `invalid` en NonverbalVocalization: precision 100%, recall 90,37%, F1 **94,34%**. TurnSense 1.1 (int8, inglés): F1 86,87 / 81,99. **No hay evaluación publicada en español** → `no publicado`.

**Corre acá.** ONNX Runtime CPU, 50 MB, ~55 ms en *su* máquina; en el i3 hay que medirlo, pero el orden de magnitud es el correcto para un gate por turno. Es la única de las cuatro cuyo modelo, tal como viene, se puede enchufar hoy sin GPU.

**Qué se adopta.** (a) La tercera clase `invalid`: mapea a `SUPPRESS` en `EotAction` y a `backchannel` en `TurnDecision`, y elimina respuestas disparadas por tos, risa o "mmm". (b) El formato chico y barato (ONNX int8, sin transformers en el camino caliente) para una cabeza acústica: el enchufe sería una clase más en `EotAction` de `eot_gate` (`RESPOND/WAIT/SUPPRESS` hoy) más un corpus de trazas que hoy no se junta. Ojo: `eot_gate.aclassify(text)` recibe **sólo texto**; TurnSense come audio+texto, así que enchufarlo exige extender el protocolo con el chunk de audio (y ahí se gana la latencia antes del ASR). **Qué no se adopta todavía:** los pesos como decisión. En español no hay número; usarlo a ciegas repite el error de elegir por moda. Se prueba con 100–200 turnos propios y se decide con la tabla.

---

## 4. VoXtream — el único que corre en esta máquina hoy

**Qué es.** TTS zero-shot **full-stream**: 0,5B parámetros, salida por frame (Mimi, 32 codebooks generados en 4 pasos: 3 AR + un paso Mixture-of-Gaussians), control de velocidad de habla ajustable **a mitad de frase**. Clonación con 3–10 s de audio de referencia (máx. 20 s), generación de hasta 5 minutos.

**Qué pide.** Camino GPU: **3 GB de VRAM** (probado en Ubuntu 22.04 / CUDA 12.8 / PyTorch 2.8; sin mención de ROCm → la RX 6500 XT no está soportada, y 3 GB sobre 4 con el escritorio encima es apretado). Camino CPU: **GGUF int8 servido por llama.cpp**, declarado correr en tiempo real **en un solo core**; el CLI baja el GGUF y se llama con `--threads 2`. Publican también `*-q8_0.gguf` + `voxtream_gguf.json` en el repo del modelo — el runtime ya está en el stack (llama.cpp), así que no suma una dependencia nueva.

**Números publicados.** RTX 3090, VoXtream2.5: **FPL (first packet latency) 30 ms, RTF 0,103**. En CPU **no publican FPL** (`no publicado`); el "tiempo real en un core" es claim del vendor, plausible para 0,5B pero sin número.

**Calidad declarada.** SEED test-en: WER 1,34%, SPK-SIM 0,714, UTMOS 3,89 (VoXtream2.5, del README).

**Licencia.** Código **MIT**. Pesos entrenados con Emilia (**CC BY-NC 4.0**) y HiFiTTS2 (CC BY 4.0): redistribuir exige atribución (ATTRIBUTION.md) y el componente NC tiñe el uso comercial. El disclaimer prohíbe clonar voces de terceros sin consentimiento — irrelevante acá (las voces son nuestras), pero anotarlo.

**Idioma.** No declara idiomas soportados y **no hay evaluación en español** (`no publicado`). El fonemizador es eSpeak NG (que tiene `es`), pero eso no garantiza prosodia rioplatense: eSpeak + modelo entrenado mayormente en inglés/chino puede sonar a traducción. **Ese es el experimento, no un supuesto.**

**Qué se adopta.** El **full-stream como contrato**: emitir audio mientras el texto todavía se está escribiendo, con la velocidad de habla como parámetro en vivo — exactamente lo que Hipotenusa necesita para que la voz arranque antes de que el LLM termine la oración (hoy lo resuelve chunking propio sobre Piper/Zonos). Se adopta **como piloto de TTS** con el prompt de 3–10 s que ya existe para Zonos. No reemplaza a Piper `es_AR-daniela-high` hasta tener números propios: primer packet y inteligibilidad en español.

---

## Qué se lleva, en una lista

1. **TurnSense `invalid`** → tercera clase del gate (`EotAction` en `eot_gate`). Se puede hacer **sin el modelo**, con las reglas actuales; después se mide el ONNX.
2. **Duplug `nonidle/speak`** → etapa acústica antes del texto, con `max_wait` como fallback; la parte textual ya está en `eot_gate` (2 etapas). Concepto, no pesos.
3. **VoXtream full-stream** → piloto de TTS en CPU/GGUF, medido contra Piper.
4. **MiniCPM-o TDM/proactivo** → ya está a medias en la sesión duplex con LFM3-Omni-2B; no hay nada nuevo que comprar.
5. **Nada de CUDA-only entra**, ni siquiera "para probar": probar acá significa portar.

## Cómo se decide (sin inventar números)

Un script, 10–20 frases rioplatenses grabadas por el usuario, mismo texto para todos:

- **TTS (VoXtream vs Piper):** primer packet (ms) en i3, y inteligibilidad/acento por escucha A/B. Criterio para cambiar el default: primer packet ≤ 120 ms **y** no peor que Piper en acento.
- **Turno (TurnSense vs gate actual):** 100–200 turnos propios etiquetados `complete/incomplete/invalid`; matriz de confusión + falsos cortes. Criterio: F1 ≥ 0,85 en `complete`/`incomplete` y `invalid` precision ≥ 0,90.
- **Duplex (LFM3 vs MiniCPM-o):** no se mide. No entra, y las cifras del card son de otra máquina.

Todo gate nuevo entra **fail-open** (error = responder), igual que `eot_gate.py` hoy: un gate que falla cerrado deja mudas a las tres voces.
