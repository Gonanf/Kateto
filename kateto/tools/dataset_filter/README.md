# dataset_filter — DRAFT

> **DRAFT**: no integrado al pipeline de voces. No toca `kateto/voices` ni `config`. Solo filtra y genera `dataset.jsonl`.

## Qué hace

1. **mmBERT ONNX (Vulkan/CPU)** — `classifier.py`: `classify_question_answer(text) -> question|answer|other`, batchable, sin CUDA. Si no hay ONNX, fallback heurístico (`?`, `¿`, regex).
2. **Filtro IA** — `ai_filter.py`: emdash `—`, frases LLM (`As an AI`, `En conclusión`, etc.), bullets perfectos. Hook `AIBinaryClassifierHook` para modelo binario opcional.
2b. **Filtro secretos** — `secrets_filter.py`: API keys y credenciales (`sk-`, `AKIA`, `ghp_`, `xoxb-`, `hf_`, `AIza`, PEM, `password=`...), token largo de alta entropía. Corre ANTES del filtro IA. Nunca loguea el secreto (usa `redact()`).
3. **Split largos** — `splitter.py`: splitea por `\n\n`, bullets, `1. 2.`, `---`. Cada chunk coherente, `min 10` / `max 800` (configurable). `TODO` sobre criterio en el archivo.
4. **Q/A + generación faltante** — `generator.py`: prompt exacto argento, llama a endpoint OpenAI-compatible (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL_NAME`). Default `http://127.0.0.1:11434/v1` (llama-server). Modelo configurable, no hardcodea `orion`. Modo `referencias` (`--mode referencias` o `DATASET_MODE=referencias`): genera el lado faltante con doble lectura, línea que sola tiene sentido y con la canción/situación (MF DOOM, NTVG, Pastillas, Cuarteto, etc.) cambia de significado; si la ref no entra sola, no entra; letra real o nada. El modelo devuelve JSON `{line, reference:{artist,work,quote,flip}}` y el pipeline guarda `reference` como metadata del par + genera un follow-up determinístico donde el usuario señala la ref y el asistente demuestra que sabe qué citó (así aprende a reconocer sus propias referencias cuando alguien las detecta).

Formato salida: `jsonl` con `{"question": "...", "answer": "...", "source_label": "question|answer|other", "source_text": "..."}` — 50% humano / 50% sintético argento.

## Uso

```bash
# deps opcionales para ONNX Vulkan
uv pip install onnxruntime tokenizers huggingface-hub openai

# dry-run (no llama a LLM, no escribe)
uv run python -m kateto.tools.dataset_filter --input hermes.db --output dataset.jsonl --dry-run --limit 100

# real (usa llama-server en 11434 o tu endpoint)
OPENAI_BASE_URL=http://127.0.0.1:11434/v1 MODEL_NAME=orion \
  uv run python -m kateto.tools.dataset_filter --input hermes.db --output dataset.jsonl --limit 500

# opciones
uv run python -m kateto.tools.dataset_filter --help
# --batch-size 32 --onnx-model-path ./model.onnx --openai-model qwen2.5 --max-chars 800 --concurrency 4
# --no-ai-filter --no-generate --no-vulkan
```

### Inputs soportados
- `hermes.db` / `.sqlite`: autodetecta tabla y columna (`text`/`content`/`message`/`body`/primera col)
- `.jsonl`: cada línea `{"text": "..."}` o texto plano
- `.json` / `.txt`

## Conversión ONNX

```python
from kateto.tools.dataset_filter.classifier import convert_to_onnx_if_needed
convert_to_onnx_if_needed("Qdrant/all-MiniLM-L6-v2", "./onnx_out")
# o usa el ONNX ya publicado: Qdrant/all-MiniLM-L6-v2-onnx
```

`onnxruntime` en Arch suele venir solo con `CPUExecutionProvider`; para Vulkan necesitás build con `--enable-vulkan` o usar `onnxruntime-vulkan`. Sin Vulkan hace fallback a CPU automáticamente.

## Estructura

```
kateto/tools/dataset_filter/
  classifier.py  — mmBERT ONNX + fallback
  ai_filter.py   — heurística + hook binario
  secrets_filter.py — API keys/tokens/credenciales + redact()
  splitter.py    — división largos
  generator.py   — prompt argento + modo referencias + OpenAI compat
  pipeline.py    — orquestación DB→jsonl
  __main__.py    — CLI
```
