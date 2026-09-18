---
id: 93
title: "mmBERT sin `huggingface-hub`/`tokenizers` muere con `'NoneType' object is not callable`"
severity: Media
status: resolved
component: kateto/classifiers/mmbert/server.py
resolved: 2026-09-17
---

## 93. mmBERT sin `huggingface-hub`/`tokenizers` muere con `'NoneType' object is not callable`

**Severidad:** Media
**Componente:** `kateto/classifiers/mmbert/server.py`

### Descripción

En un venv con el extra `classifier` incompleto (`onnxruntime` presente pero `huggingface_hub` y `tokenizers` ausentes), el arranque moría con `'NoneType' object is not callable`, sin indicar qué instalar.

### Impacto

Error críptico que no apunta a la dependencia faltante; el extra `classifier` no se instala solo con `uv run` (los opcionales requieren `--extra`).

### Causa

`server.py` hacía `hf_hub_download = None` / `Tokenizer = None` ante `ImportError`, pero `_resolve_model_path` y `_load_tokenizer` los invocaban sin verificar. El guard de `MmBertClassifierProvider` solo capturaba `ImportError` del import del módulo, que nunca se producía gracias a los guards de nivel módulo.

### Solución aplicada

- `_require_hub_deps()` en `server.py`: falla rápido con `RuntimeError` accionable (`uv run --extra classifier kateto run` o `uv tool install 'kateto[classifier]'`), invocado desde `_resolve_model_path` y `_load_tokenizer`.
- Fix inmediato para el usuario: `uv run --extra classifier kateto run`.

**Archivos:** `kateto/classifiers/mmbert/server.py`, `kateto/tests/test_mmbert_classifier.py`
