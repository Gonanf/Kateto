"""
BERT classifier retraining pipeline for talk/think intent classification.

CLI usage:
    python -m trainer.train_bert --data data/processed/classifier --output output/classifier --epochs 3
    python -m trainer.train_bert --csv data/raw/classifier/coarse_grained.csv --output output/classifier

Uses DistilBERT base (distilbert-base-uncased) matching the existing classifier
in apps/classifier/. The saved model is compatible with apps/classifier/server.py:

    AutoModelForSequenceClassification.from_pretrained(
        output_dir,
        id2label={0: "talk", 1: "think"},
        label2id={"talk": 0, "think": 1},
    )

Evaluation outputs: accuracy, precision, recall, F1, and confusion matrix (JSON).
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from datasets import Dataset, DatasetDict, load_from_disk
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

logger = logging.getLogger(__name__)

LABEL2ID = {"talk": 0, "think": 1}
ID2LABEL = {0: "talk", 1: "think"}
MODEL_NAME = "distilbert-base-uncased"


def compute_metrics(eval_pred):
    """Compute accuracy, precision, recall, F1 from predictions.

    Parameters
    ----------
    eval_pred : EvalPrediction
        Named tuple with ``predictions`` (logits) and ``label_ids``.

    Returns
    -------
    dict[str, float]
        Metrics dictionary with keys: accuracy, precision, recall, f1.
    """
    predictions, labels = eval_pred
    predictions = predictions.argmax(axis=-1)
    acc = accuracy_score(labels, predictions)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, average="binary"
    )
    return {
        "accuracy": float(acc),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
    }


def load_csv_dataset(csv_path: str | Path) -> Dataset:
    """Load a CSV file with ``text,label`` columns and convert to Dataset.

    Parameters
    ----------
    csv_path : str | Path
        Path to a CSV file with columns ``text`` and ``label``.
        Labels should be ``"talk"`` or ``"think"`` (case-insensitive).

    Returns
    -------
    Dataset
        HuggingFace Dataset with ``text`` and ``label`` (int) columns.
        Labels mapped: talk→0, think→1.

    Raises
    ------
    FileNotFoundError
        If the CSV path does not exist.
    ValueError
        If required columns are missing.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV path does not exist: {path}")

    df = pd.read_csv(path)
    required_cols = {"text", "label"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df["label"] = df["label"].str.strip().str.lower().map(LABEL2ID)

    na_mask = df["label"].isna()
    if na_mask.any():
        logger.warning("Dropping %d rows with unmapped labels", na_mask.sum())
        df = df.dropna(subset=["label"])

    df["label"] = df["label"].astype(int)

    ds = Dataset.from_pandas(df)
    if "__index_level_0__" in ds.column_names:
        ds = ds.remove_columns(["__index_level_0__"])

    logger.info("Loaded %d rows from CSV: %s", len(ds), path)
    return ds


def load_processed_dataset(data_path: str | Path) -> DatasetDict | Dataset:
    """Load a HuggingFace Dataset or DatasetDict from disk (Arrow format).

    Parameters
    ----------
    data_path : str | Path
        Path to a saved HuggingFace Dataset directory.

    Returns
    -------
    Dataset | DatasetDict
        Loaded dataset — either a single ``Dataset`` or a pre-split ``DatasetDict``.

    Raises
    ------
    FileNotFoundError
        If the path does not exist.
    """
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Data path does not exist: {path}")

    ds = load_from_disk(str(path))
    if isinstance(ds, DatasetDict):
        logger.info(
            "Loaded DatasetDict from %s (%s)",
            path,
            {k: len(v) for k, v in ds.items()},
        )
    else:
        logger.info("Loaded Dataset from %s (%d rows)", path, len(ds))
    return ds


def tokenize_dataset(
    dataset: Dataset,
    tokenizer: AutoTokenizer,
    max_length: int = 128,
) -> Dataset:
    """Tokenize a dataset if it hasn't been tokenized yet.

    Parameters
    ----------
    dataset : Dataset
        Dataset with a ``text`` column, or already tokenized
        (has ``input_ids`` column).
    tokenizer : AutoTokenizer
        HuggingFace tokenizer instance.
    max_length : int
        Maximum sequence length (default 128).

    Returns
    -------
    Dataset
        Tokenized dataset with ``input_ids``, ``attention_mask``, ``label``.
        The ``text`` column is removed after tokenization.
    """
    if "input_ids" in dataset.column_names:
        logger.info("Dataset already tokenized — skipping tokenization")
        return dataset

    def _tokenize(batch: dict[str, list]) -> dict[str, list]:
        return tokenizer(
            batch["text"],
            truncation=True,
            padding="max_length",
            max_length=max_length,
        )

    dataset = dataset.map(_tokenize, batched=True, remove_columns=["text"])
    logger.info("Tokenized dataset (%d rows, max_length=%d)", len(dataset), max_length)
    return dataset


def compute_confusion_matrix(trainer: Trainer, dataset: Dataset) -> dict:
    """Compute confusion matrix on an evaluation dataset.

    Parameters
    ----------
    trainer : Trainer
        Trained HuggingFace Trainer.
    dataset : Dataset
        Evaluation dataset with ``label`` column.

    Returns
    -------
    dict
        Serializable confusion matrix:
        ``{"matrix": [[tn, fp], [fn, tp]], "labels": ["talk", "think"]}``.
    """
    predictions = trainer.predict(dataset)
    preds = predictions.predictions.argmax(axis=-1)
    labels = predictions.label_ids

    cm = confusion_matrix(labels, preds).tolist()
    return {
        "matrix": cm,
        "labels": ["talk", "think"],
    }


def train_bert(
    data_path: Optional[str] = None,
    csv_path: Optional[str] = None,
    output_dir: str = "output/classifier",
    epochs: int = 3,
    batch_size: int = 8,
    lr: float = 2e-5,
    max_length: int = 128,
) -> None:
    """Train a DistilBERT classifier for talk/think intent classification.

    This is the main training pipeline. It:

    1. Loads data from a processed HuggingFace Dataset (Arrow format) or CSV
    2. Tokenizes with ``distilbert-base-uncased`` tokenizer
    3. Splits into train/test (80/20) if not pre-split
    4. Initializes ``distilbert-base-uncased`` with 2 output labels
    5. Trains with HuggingFace ``Trainer``
    6. Evaluates: accuracy, precision, recall, F1
    7. Generates confusion matrix
    8. Saves model checkpoint + ``metrics.json``

    Parameters
    ----------
    data_path : str | None
        Path to a processed HuggingFace Dataset directory.
        Mutual exclusive with ``csv_path``.
    csv_path : str | None
        Path to a raw CSV file with ``text,label`` columns (fallback).
        Mutual exclusive with ``data_path``.
    output_dir : str
        Output directory for model checkpoint and metrics JSON.
    epochs : int
        Number of training epochs (default 3).
    batch_size : int
        Per-device training batch size (default 8).
    lr : float
        Learning rate (default 2e-5).
    max_length : int
        Maximum token sequence length (default 128).

    Raises
    ------
    ValueError
        If neither ``data_path`` nor ``csv_path`` is provided.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if data_path:
        dataset = load_processed_dataset(data_path)
    elif csv_path:
        dataset = load_csv_dataset(csv_path)
    else:
        raise ValueError("Either --data or --csv must be provided")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    if isinstance(dataset, DatasetDict):
        tokenized = {}
        for split_name, split_ds in dataset.items():
            tokenized[split_name] = tokenize_dataset(
                split_ds, tokenizer, max_length=max_length
            )
        dataset = DatasetDict(tokenized)
    else:
        dataset = tokenize_dataset(dataset, tokenizer, max_length=max_length)

    if isinstance(dataset, DatasetDict):
        train_dataset = dataset["train"]
        eval_dataset = dataset.get("test", dataset.get("validation"))
        if eval_dataset is None:
            keys = [k for k in dataset.keys() if k != "train"]
            if keys:
                eval_dataset = dataset[keys[0]]
            else:
                raise ValueError("DatasetDict has no test/validation split")
        logger.info(
            "Using pre-split dataset: %d train, %d eval",
            len(train_dataset),
            len(eval_dataset),
        )
    else:
        split = dataset.train_test_split(test_size=0.2, seed=42)
        train_dataset = split["train"]
        eval_dataset = split["test"]
        logger.info(
            "Split dataset 80/20: %d train, %d eval",
            len(train_dataset),
            len(eval_dataset),
        )

    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=2,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    args = TrainingArguments(
        output_dir=str(output_path),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="epoch",
        learning_rate=lr,
        fp16=True,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        save_total_limit=2,
        report_to="none",
        seed=42,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    logger.info(
        "Starting training (%d epochs, batch_size=%d, lr=%e)",
        epochs,
        batch_size,
        lr,
    )
    trainer.train()

    logger.info("Running final evaluation...")
    eval_metrics = trainer.evaluate()
    logger.info("Evaluation metrics: %s", eval_metrics)

    cm_data = compute_confusion_matrix(trainer, eval_dataset)
    logger.info(
        "Confusion matrix:\n  TN=%-4d FP=%-4d\n  FN=%-4d TP=%-4d",
        cm_data["matrix"][0][0],
        cm_data["matrix"][0][1],
        cm_data["matrix"][1][0],
        cm_data["matrix"][1][1],
    )

    model.save_pretrained(str(output_path))
    tokenizer.save_pretrained(str(output_path))
    logger.info("Model saved to %s", output_path)

    metrics = {
        "eval": eval_metrics,
        "confusion_matrix": cm_data,
        "training": {
            "epochs": epochs,
            "batch_size": batch_size,
            "learning_rate": lr,
            "model_name": MODEL_NAME,
            "train_samples": len(train_dataset),
            "eval_samples": len(eval_dataset),
        },
    }
    metrics_path = output_path / "metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    logger.info("Metrics saved to %s", metrics_path)

    print("\n" + "=" * 60)
    print("Training complete!")
    print(f"  Model:     {output_path}")
    print(f"  Accuracy:  {eval_metrics.get('eval_accuracy', 'N/A'):.4f}")
    print(f"  Precision: {eval_metrics.get('eval_precision', 'N/A'):.4f}")
    print(f"  Recall:    {eval_metrics.get('eval_recall', 'N/A'):.4f}")
    print(f"  F1:        {eval_metrics.get('eval_f1', 'N/A'):.4f}")
    print(f"  Metrics:   {metrics_path}")
    print("=" * 60)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Train DistilBERT classifier for talk/think intent classification",
    )

    data_group = parser.add_mutually_exclusive_group(required=True)
    data_group.add_argument(
        "--data",
        type=str,
        default=None,
        help="Path to processed HuggingFace Dataset directory (Arrow format)",
    )
    data_group.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to raw CSV file with text,label columns (fallback)",
    )

    parser.add_argument(
        "--output",
        type=str,
        default="output/classifier",
        help="Output directory for model checkpoint and metrics (default: output/classifier)",
    )

    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        dest="batch_size",
        help="Per-device training batch size (default: 8)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=2e-5,
        help="Learning rate (default: 2e-5)",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=128,
        dest="max_length",
        help="Maximum token sequence length (default: 128)",
    )

    return parser.parse_args(argv)


def main() -> None:
    """Entry point for ``python -m trainer.train_bert``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args()

    train_bert(
        data_path=args.data,
        csv_path=args.csv,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        max_length=args.max_length,
    )


if __name__ == "__main__":
    main()
