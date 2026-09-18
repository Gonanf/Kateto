---
id: 89
title: "Classifier trata `model = \"classifier\"` como repo ID de HuggingFace y falla con 401"
severity: Media
status: resolved
component: kateto/providers/classifier.py, config/defaults/config.toml
resolved: 2026-09-17
---

## 89. Classifier trata `model = "classifier"` como repo ID de HuggingFace y falla con 401

**Severidad:** Media
**Componente:** `kateto/providers/classifier.py`, `config/defaults/config.toml`

### Descripción

Con `executor_classifier.model = "classifier"` en la config, el proveedor mmBERT usaba ese valor como `repo_id` de HuggingFace Hub en vez del modelo por defecto (`Qdrant/all-MiniLM-L6-v2-onnx`). El `tokenizer.json` sí descargaba (del repo correcto por fallback), pero `model.onnx` devolvía `401 Unauthorized` / `Repository Not Found` para `https://huggingface.co/classifier/resolve/main/model.onnx`.

### Impacto

Clasificación de intenciones caída: ninguna transcripción se ruteaba a voces.

### Causa

`MmBertClassifierProvider` resolvía `self._model = model or settings.model or "Qdrant/..."` (`kateto/providers/classifier.py:257`), y `_resolve_model_path` trataba cualquier valor no existente en disco como repo ID remoto. El template de `config/defaults/config.toml` traía `model = "classifier"` como placeholder.

### Solución aplicada

Configuración del usuario corregida a:

```toml
[plugin]
executor_classifier.backend = "mmbert"
executor_classifier.model = "Qdrant/all-MiniLM-L6-v2-onnx"
```

**Archivos:** `kateto/providers/classifier.py`, `config/defaults/config.toml`
