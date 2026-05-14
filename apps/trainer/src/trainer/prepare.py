"""
Data preparation module for the trainer fine-tuning pipeline.

Provides deduplication, dataset splitting, format conversion, and
tokenization utilities. All functions work with the standard dict schema
from collect.py:

    {"text": str, "label": str, "source": str, ...}

Dependencies:
    - datasets (HuggingFace) for tokenize/save/load functions
    - transformers tokenizer for tokenize_* functions
    - stdlib only for deduplicate, split, format functions
"""

import logging
import random
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from datasets import Dataset

logger = logging.getLogger(__name__)


# ─── Deduplication ───────────────────────────────────────────────────────────


def _jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity on 4-gram sets between two strings."""
    a_grams = {a[i : i + 4] for i in range(len(a) - 3)}
    b_grams = {b[i : i + 4] for i in range(len(b) - 3)}
    intersection = len(a_grams & b_grams)
    union = len(a_grams | b_grams)
    return intersection / union if union > 0 else 0.0


def deduplicate(
    items: list[dict],
    key: str = "text",
    threshold: float = 0.85,
    dedup_keys: Optional[list[str]] = None,
) -> list[dict]:
    """
    Remove near-duplicate items using Jaccard similarity on character 4-grams.

    Parameters
    ----------
    items : list[dict]
        List of dicts conforming to the standard schema.
    key : str
        Field name to compare when *dedup_keys* is not provided.
    threshold : float
        Jaccard similarity threshold (0-1). Items above this are considered
        duplicates and removed (first occurrence is kept).
    dedup_keys : list[str] | None
        If provided, similarity is computed on the concatenation of these
        fields (e.g. ``["text", "output"]``). Overrides *key*.

    Returns
    -------
    list[dict]
        Filtered list preserving original order.
    """
    if not items:
        return items

    def _get_text(item: dict) -> str:
        if dedup_keys:
            parts = []
            for f in dedup_keys:
                val = item.get(f)
                if isinstance(val, str):
                    parts.append(val)
                elif isinstance(val, dict):
                    # Handle nested input: {"input": "...", "silence": True}
                    inner = val.get("input", "")
                    if isinstance(inner, str):
                        parts.append(inner)
            return " ".join(parts)
        val = item.get(key, "")
        if isinstance(val, dict):
            val = val.get("input", "")
        return val if isinstance(val, str) else ""

    kept: list[dict] = []
    seen_texts: list[str] = []

    for item in items:
        text = _get_text(item)
        if not text:
            # Always keep items with empty comparison text
            kept.append(item)
            continue

        is_dup = False
        for seen in seen_texts:
            if _jaccard_similarity(text, seen) >= threshold:
                is_dup = True
                break

        if not is_dup:
            kept.append(item)
            seen_texts.append(text)

    removed = len(items) - len(kept)
    pct = (removed / len(items)) * 100 if items else 0.0
    logger.info(
        "Dedup: %d → %d (%.1f%% removed)", len(items), len(kept), pct
    )
    return kept


# ─── Train/Validation Split ──────────────────────────────────────────────────


def split_train_val(
    items: list[dict],
    val_split: float = 0.2,
    stratify_key: Optional[str] = "label",
) -> tuple[list[dict], list[dict]]:
    """
    Stratified train/validation split preserving label distribution.

    Parameters
    ----------
    items : list[dict]
        List of dicts with at least ``*stratify_key*`` field.
    val_split : float
        Fraction of items to assign to validation set (0-1).
    stratify_key : str | None
        Field name to stratify by. If ``None``, a random shuffle split
        is performed without stratification.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(train_items, val_items)``.
    """
    rng = random.Random(42)

    if stratify_key is None:
        indices = list(range(len(items)))
        rng.shuffle(indices)
        split_idx = int(len(indices) * (1 - val_split))
        train_idx = indices[:split_idx]
        val_idx = indices[split_idx:]
        return [items[i] for i in train_idx], [items[i] for i in val_idx]

    # Group items by label
    groups: dict[str, list[int]] = {}
    for i, item in enumerate(items):
        label = str(item.get(stratify_key, "unknown"))
        groups.setdefault(label, []).append(i)

    train_indices: list[int] = []
    val_indices: list[int] = []

    for label, indices in groups.items():
        rng.shuffle(indices)
        split_idx = max(1, int(len(indices) * (1 - val_split)))
        if split_idx >= len(indices):
            # Ensure at least 1 item in each split when possible
            split_idx = len(indices) - 1 if len(indices) > 1 else len(indices)
        train_indices.extend(indices[:split_idx])
        val_indices.extend(indices[split_idx:])

    # Build result sets maintaining original order
    train_set = set(train_indices)
    val_set = set(val_indices)

    train_items = [items[i] for i in range(len(items)) if i in train_set]
    val_items = [items[i] for i in range(len(items)) if i in val_set]

    return train_items, val_items


# ─── Format Conversion ───────────────────────────────────────────────────────


def _extract_user_text(item: dict) -> str:
    """Extract the user message from an item, if available."""
    # Direct input field (from training datasets)
    inp = item.get("input")
    if isinstance(inp, str):
        return inp
    # Nested input: {"input": "...", "silence": True}
    if isinstance(inp, dict):
        inner = inp.get("input", "")
        if isinstance(inner, str):
            return inner
    return ""


def _extract_assistant_text(item: dict) -> str:
    """Extract the assistant response from an item."""
    text = item.get("text", "")
    if text:
        return text
    # Fall back to output field (training datasets)
    output = item.get("output", "")
    if output:
        # Extract content inside <response> tags if present
        if isinstance(output, str) and "<response>" in output:
            start = output.find("<response>") + len("<response>")
            end = output.find("</response>", start)
            if end > start:
                return output[start:end]
        return output if isinstance(output, str) else ""
    return ""


def format_chatml(
    items: list[dict],
    system_prompt: str = "",
) -> list[dict]:
    """
    Convert items to ChatML format for LLM fine-tuning.

    Items with user→assistant pairs (convos, training) are split accordingly.
    Single items (blogs, xavier) are wrapped with a generic user prompt.

    Parameters
    ----------
    items : list[dict]
        List of dicts with at least ``text``, ``label``, ``source``.
    system_prompt : str
        Optional system prompt prepended to all examples.

    Returns
    -------
    list[dict]
        Each dict has ``text`` (ChatML-formatted), ``label``, and ``source``.
    """
    SYSTEM_BLOCK = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n" if system_prompt else ""
    )
    result: list[dict] = []

    for item in items:
        user_text = _extract_user_text(item)
        assistant_text = _extract_assistant_text(item)
        label = item.get("label", "")
        source = item.get("source", "")

        # Determine user prompt based on label/source
        if not user_text:
            if label == "user_blog" or source == "blogs":
                user_text = "Escribe como si fueras vos"
            elif label == "xavier_quote" or source == "xavier":
                # Use a short prefix from the assistant text as context
                prefix = assistant_text[:80].strip()
                user_text = f"Habla como Xavier sobre: {prefix}..." if prefix else "Habla como Xavier"
            else:
                user_text = "Continuá"

        chatml_text = (
            f"{SYSTEM_BLOCK}"
            f"<|im_start|>user\n{user_text}<|im_end|>\n"
            f"<|im_start|>assistant\n{assistant_text}<|im_end|>"
        )

        result.append({
            "text": chatml_text,
            "label": label,
            "source": source,
        })

    return result


def format_classification(items: list[dict]) -> list[dict]:
    """
    Convert items to BERT-style classification format.

    Label mapping:
        ``"talk"`` / ``"talker_response"`` → 0
        ``"think"`` / ``"thinker_output"`` → 1

    Other labels are mapped to 0 by default.

    Parameters
    ----------
    items : list[dict]
        List of dicts with at least ``text`` and ``label``.

    Returns
    -------
    list[dict]
        Each dict has ``text`` and ``label`` (int 0 or 1).
    """
    LABEL_MAP = {
        "talk": 0,
        "talker_response": 0,
        "think": 1,
        "thinker_output": 1,
    }

    result: list[dict] = []
    for item in items:
        raw_label = item.get("label", "")
        text = item.get("text", "")
        # Fall back to output field if text is empty
        if not text:
            text = item.get("output", "")
            if isinstance(text, dict):
                text = str(text.get("input", ""))
        if not isinstance(text, str):
            text = str(text)

        numeric_label = LABEL_MAP.get(raw_label, 0)
        result.append({"text": text, "label": numeric_label})

    return result


# ─── Tokenization ────────────────────────────────────────────────────────────


def tokenize_llm(
    items: list[dict],
    tokenizer: Any,
    max_length: int = 512,
) -> "Dataset":
    """
    Tokenize items for LLM fine-tuning (e.g. Qwen, Llama).

    Parameters
    ----------
    items : list[dict]
        List of dicts with a ``text`` field (ChatML-formatted preferred).
    tokenizer
        HuggingFace tokenizer instance.
    max_length : int
        Maximum sequence length (default 512).

    Returns
    -------
    Dataset
        HuggingFace ``datasets.Dataset`` with ``input_ids``, ``attention_mask``,
        and ``labels`` columns.
    """
    from datasets import Dataset  # fmt: skip

    texts = [item.get("text", "") for item in items]

    def tokenize_fn(examples: dict[str, list]) -> dict[str, Any]:
        tokenized = tokenizer(
            examples["text"],
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors=None,
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    ds = Dataset.from_list([{"text": t} for t in texts])
    ds = ds.map(tokenize_fn, batched=True, remove_columns=["text"])

    return ds


def tokenize_bert(
    items: list[dict],
    tokenizer: Any,
    max_length: int = 128,
) -> "Dataset":
    """
    Tokenize items for BERT classification fine-tuning.

    Parameters
    ----------
    items : list[dict]
        List of dicts with ``text`` (str) and ``label`` (int 0/1).
    tokenizer
        HuggingFace tokenizer instance.
    max_length : int
        Maximum sequence length (default 128).

    Returns
    -------
    Dataset
        HuggingFace ``datasets.Dataset`` with ``input_ids``, ``attention_mask``,
        and ``label`` columns.
    """
    from datasets import Dataset  # fmt: skip

    def tokenize_fn(examples: dict[str, list]) -> dict[str, Any]:
        tokenized = tokenizer(
            examples["text"],
            truncation=True,
            padding="max_length",
            max_length=max_length,
            return_tensors=None,
        )
        return tokenized

    ds = Dataset.from_list(items)
    ds = ds.map(tokenize_fn, batched=True, remove_columns=["text"])

    return ds


# ─── Save / Load ─────────────────────────────────────────────────────────────


def save_processed(dataset: "Dataset", path: str | Path) -> None:
    """
    Save a HuggingFace Dataset to disk in Arrow format.

    Parameters
    ----------
    dataset : Dataset
        HuggingFace ``datasets.Dataset`` instance.
    path : str | Path
        Destination directory path.
    """
    from datasets import Dataset  # fmt: skip # noqa: F401 — imported for type hint resolution

    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    dataset.save_to_disk(str(path))
    logger.info("Saved processed dataset to %s (%d rows)", path, len(dataset))


def load_processed(path: str | Path) -> "Dataset":
    """
    Load a HuggingFace Dataset from disk (Arrow format).

    Parameters
    ----------
    path : str | Path
        Path to the saved dataset directory.

    Returns
    -------
    Dataset
        Loaded HuggingFace ``datasets.Dataset``.
    """
    from datasets import Dataset  # fmt: skip # noqa: F401

    path = Path(path)
    ds = Dataset.load_from_disk(str(path))  # type: ignore[attr-defined]
    logger.info("Loaded processed dataset from %s (%d rows)", path, len(ds))
    return ds
