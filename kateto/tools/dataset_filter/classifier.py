"""
mmBERT ONNX classifier for Vulkan (onnxruntime) — DRAFT.

* Sin CUDA: solo CPU + opcional VulkanExecutionProvider.
* Función requerida: classify_question_answer(text) -> 'question'|'answer'|'other'
* Batchable: classify_batch(texts) -> list[str]
* Si no hay ONNX, fallback heurístico + hook para conversión.
"""
from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Literal

import numpy as np

log = logging.getLogger("dataset_filter.classifier")

Label = Literal["question", "answer", "other"]

# Prototipos Q/A/Other para mmBERT sin fine-tuning — centroid cosine.
# Si tenés un checkpoint fine-tuneado Q/A, reemplazá PROTOTYPES y/o cargá ONNX clasificador directo.
PROTOTYPES: dict[str, list[str]] = {
    "question": [
        "¿qué opinás de Milei?",
        "¿por qué el dólar sube tanto?",
        "¿me explicás cómo funciona eso?",
        "¿cuál es el sentido de la vida?",
        "¿vos qué harías en mi lugar?",
        "¿te parece que vamos a salir campeones?",
        "che, ¿cómo andás?",
        "¿por qué los políticos mienten tanto?",
        "¿qué significa ser feliz?",
        "how does this work exactly?",
    ],
    "answer": [
        "Mirá, yo creo que la cosa es así, sin vueltas.",
        "Es simple: hacé lo que te parezca y bancátela.",
        "Te digo la posta: nadie tiene la respuesta, todos chamuyan.",
        "Jajaja sos un boludo, pero te quiero igual.",
        "La vida es como el mate: amarga al principio, después te acostumbrás.",
        "No te comas la cabeza, ya va a salir.",
        "Eso es verso, no le creas nada.",
        "Filosóficamente hablando, todo es un invento del capitalismo.",
    ],
    "other": [
        "ok",
        "jajaja",
        "https://example.com",
        "👍👍👍",
        "lol",
        "— — —",
        "• item suelto sin contexto",
        "12345",
    ],
}

CATEGORIES: tuple[str, ...] = ("question", "answer", "other")
MODEL_REPO = "Qdrant/all-MiniLM-L6-v2-onnx"
ONNX_FILENAME = "model.onnx"

# Regex rápida para fallback sin modelo
_Q_RE = re.compile(r"\?\s*$|\b(qué|quién|cómo|cuándo|dónde|por qué|cuál|cuanto)\b|¿", re.I)


def _heur_classify(text: str) -> Label:
    t = text.strip()
    if not t or len(t) < 3:
        return "other"
    if "?" in t or "¿" in t or _Q_RE.search(t):
        return "question"
    # muy corto / solo emoji / url -> other
    if len(t.split()) < 2 or t.startswith("http"):
        return "other"
    return "answer"


class MmBertQAClassifier:
    """Wrapper ONNX para Q/A. Usa Vulkan si está disponible, sino CPU."""

    def __init__(
        self,
        onnx_path: str | Path | None = None,
        *,
        use_vulkan: bool = True,
        model_repo: str = MODEL_REPO,
    ) -> None:
        self.onnx_path = Path(onnx_path) if onnx_path else None
        self.model_repo = model_repo
        self.use_vulkan = use_vulkan
        self.session = None
        self.tokenizer = None
        self._centroids: dict[str, np.ndarray] | None = None
        self._available = False
        self._try_load()

    # -- carga ---------------------------------------------------------------

    def _try_load(self) -> None:
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            log.warning("onnxruntime no instalado — fallback heurístico (pip install onnxruntime tokenizers huggingface-hub)")
            return
        try:
            from tokenizers import Tokenizer  # type: ignore
            from huggingface_hub import hf_hub_download  # type: ignore
        except ImportError as e:
            log.warning("faltan deps classifier: %s — fallback heurístico", e)
            return

        # resolver modelo
        model_file: Path | None = None
        if self.onnx_path and self.onnx_path.exists():
            model_file = self.onnx_path if self.onnx_path.is_file() else self.onnx_path / ONNX_FILENAME
            tokenizer_repo = self.model_repo
        else:
            # intentar hf_hub_download; si onnx_path es repo id, usarlo
            repo = str(self.onnx_path) if self.onnx_path and not self.onnx_path.exists() else self.model_repo
            try:
                model_file = Path(hf_hub_download(repo_id=repo, filename=ONNX_FILENAME, local_files_only=False))
                tokenizer_repo = repo
            except Exception as e:
                log.warning("no se pudo bajar ONNX %s: %s — fallback heurístico", repo, e)
                return

        # tokenizer
        try:
            tok_path = hf_hub_download(repo_id=tokenizer_repo, filename="tokenizer.json", local_files_only=False)
            self.tokenizer = Tokenizer.from_file(tok_path)
        except Exception as e:
            log.warning("no se pudo cargar tokenizer: %s", e)
            return

        # session — Vulkan primero, fallback CPU sin CUDA
        opts = ort.SessionOptions()
        try:
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        except Exception:
            pass
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = True
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1

        providers: list[str] = []
        if self.use_vulkan:
            providers.append("VulkanExecutionProvider")
        providers.append("CPUExecutionProvider")

        try:
            self.session = ort.InferenceSession(str(model_file), sess_options=opts, providers=providers)
        except Exception as e:
            if "Vulkan" in str(e):
                log.warning("Vulkan no disponible (%s), fallback CPU", e)
                self.session = ort.InferenceSession(str(model_file), sess_options=opts, providers=["CPUExecutionProvider"])
            else:
                log.warning("no se pudo crear session ONNX: %s", e)
                return
        log.info("ONNX providers activos: %s", self.session.get_providers())
        # construir centroids
        try:
            self._build_centroids()
            self._available = True
            log.info("mmBERT Q/A classifier listo (%d cats)", len(CATEGORIES))
        except Exception as e:
            log.warning("falló build centroids: %s", e)

    def _tokenize(self, texts: list[str], max_length: int = 128) -> dict[str, np.ndarray]:
        assert self.tokenizer is not None
        enc = self.tokenizer.encode_batch(texts)
        n = len(texts)
        input_ids = np.zeros((n, max_length), dtype=np.int64)
        attention_mask = np.zeros((n, max_length), dtype=np.int64)
        token_type_ids = np.zeros((n, max_length), dtype=np.int64)
        for i, e in enumerate(enc):
            ids = e.ids[:max_length]
            input_ids[i, : len(ids)] = ids
            attention_mask[i, : len(ids)] = 1
        return {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids}

    def _embed(self, texts: list[str]) -> np.ndarray:
        assert self.session is not None
        inputs = self._tokenize(texts)
        out = self.session.run(None, inputs)
        last_hidden = out[0]  # (N, L, 384)
        mask = inputs["attention_mask"].astype(np.float32)[:, :, None]
        summed = np.sum(last_hidden * mask, axis=1)
        counts = np.maximum(mask.sum(axis=1), 1e-9)
        emb = summed / counts
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        return emb / norms

    def _build_centroids(self) -> None:
        assert self.session is not None and self.tokenizer is not None
        self._centroids = {}
        for cat, sents in PROTOTYPES.items():
            emb = self._embed(sents)
            c = emb.mean(axis=0)
            c /= np.linalg.norm(c) or 1
            self._centroids[cat] = c

    # -- API pública ---------------------------------------------------------

    def classify(self, text: str) -> Label:
        if not self._available or self._centroids is None:
            return _heur_classify(text)
        try:
            emb = self._embed([text])[0]
            sims = np.array([float(np.dot(emb, self._centroids[c])) for c in CATEGORIES])
            return CATEGORIES[int(np.argmax(sims))]  # type: ignore[return-value]
        except Exception as e:
            log.debug("classify fallback heurístico: %s", e)
            return _heur_classify(text)

    def classify_batch(self, texts: list[str]) -> list[Label]:
        if not self._available or self._centroids is None:
            return [_heur_classify(t) for t in texts]
        try:
            embs = self._embed(texts)
            sims = np.array([[float(np.dot(e, self._centroids[c])) for c in CATEGORIES] for e in embs])
            idx = np.argmax(sims, axis=1)
            return [CATEGORIES[i] for i in idx]  # type: ignore
        except Exception as e:
            log.debug("classify_batch fallback: %s", e)
            return [_heur_classify(t) for t in texts]

    @property
    def is_onnx(self) -> bool:
        return self._available


# Singleton perezoso para classify_question_answer simple
_default: MmBertQAClassifier | None = None


def _get_default() -> MmBertQAClassifier:
    global _default
    if _default is None:
        onnx_env = os.getenv("MMBERT_ONNX_PATH") or os.getenv("ONNX_MODEL_PATH")
        use_vulkan = os.getenv("MMBERT_NO_VULKAN") != "1"
        _default = MmBertQAClassifier(onnx_path=onnx_env, use_vulkan=use_vulkan)
    return _default


def classify_question_answer(text: str) -> Label:
    """Clasifica texto en 'question' | 'answer' | 'other'. Batchable vía classify_batch."""
    return _get_default().classify(text)


def classify_batch(texts: list[str]) -> list[Label]:
    return _get_default().classify_batch(texts)


def convert_to_onnx_if_needed(model_id: str = "Qdrant/all-MiniLM-L6-v2", output_dir: str | Path = "./onnx_out") -> Path | None:
    """
    Hook para convertir HF -> ONNX con optimum si hace falta.
    No se ejecuta automáticamente; llamalo manual si tu modelo no tiene onnx.
    Requiere: pip install optimum[onnxruntime] transformers
    """
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction  # type: ignore
        from transformers import AutoTokenizer  # type: ignore
    except ImportError:
        log.error("optimum/transformers no instalados — pip install optimum[onnxruntime] transformers")
        return None
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    log.info("convirtiendo %s -> ONNX en %s", model_id, out)
    model = ORTModelForFeatureExtraction.from_pretrained(model_id, export=True)
    tok = AutoTokenizer.from_pretrained(model_id)
    model.save_pretrained(out)
    tok.save_pretrained(out)
    log.info("ONNX guardado en %s", out)
    return out / "model.onnx"
