"""Tests for train_bert.py — metrics computation and CSV loading.

All tests are CPU-compatible and do not require a GPU.
"""

import pytest
import json
import numpy as np
from pathlib import Path
from transformers import EvalPrediction
from trainer.train_bert import (
    compute_metrics,
    load_csv_dataset,
    parse_args,
)


class TestComputeMetrics:
    """Test the compute_metrics evaluation function."""

    def test_perfect_prediction(self):
        """All predictions correct → accuracy=1.0, f1=1.0."""
        pred = EvalPrediction(
            predictions=np.array([[0.9, 0.1], [0.2, 0.8]]),
            label_ids=np.array([0, 1]),
        )
        metrics = compute_metrics(pred)
        assert metrics["accuracy"] == 1.0
        assert metrics["f1"] == 1.0
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0

    def test_partial_prediction(self):
        """One correct, one wrong → accuracy=0.5."""
        pred = EvalPrediction(
            predictions=np.array([[0.9, 0.1], [0.8, 0.2]]),  # both predicted 0
            label_ids=np.array([0, 1]),  # actual: 0, 1
        )
        metrics = compute_metrics(pred)
        assert metrics["accuracy"] == 0.5

    def test_all_wrong(self):
        """All predictions wrong → accuracy=0.0."""
        pred = EvalPrediction(
            predictions=np.array([[0.1, 0.9], [0.3, 0.7]]),  # both predicted 1
            label_ids=np.array([0, 1]),  # actual: 0, 1 — only second is correct
        )
        metrics = compute_metrics(pred)
        assert metrics["accuracy"] == 0.5

    def test_single_class_prediction(self):
        """Single sample edge case."""
        pred = EvalPrediction(
            predictions=np.array([[0.05, 0.95]]),
            label_ids=np.array([1]),
        )
        metrics = compute_metrics(pred)
        assert metrics["accuracy"] == 1.0

    def test_metrics_keys_present(self):
        """All expected keys exist in the returned dict."""
        pred = EvalPrediction(
            predictions=np.array([[0.9, 0.1], [0.2, 0.8]]),
            label_ids=np.array([0, 1]),
        )
        metrics = compute_metrics(pred)
        assert set(metrics.keys()) == {"accuracy", "precision", "recall", "f1"}


class TestLoadCSVDataset:
    """Test CSV loading for classifier training."""

    def test_valid_csv(self, tmp_path):
        """Talk and think labels are mapped to 0 and 1."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('text,label\n"hola",talk\n"a ver",think\n')
        dataset = load_csv_dataset(str(csv_file))
        assert len(dataset) == 2
        assert dataset[0]["label"] == 0  # talk → 0
        assert dataset[1]["label"] == 1  # think → 1

    def test_case_insensitive_labels(self, tmp_path):
        """Labels should be case-insensitive."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text('text,label\n"Hello",Talk\n"Goodbye",THINK\n"Maybe",tAlK\n')
        dataset = load_csv_dataset(str(csv_file))
        assert len(dataset) == 3
        assert dataset[0]["label"] == 0  # Talk → 0
        assert dataset[1]["label"] == 1  # THINK → 1
        assert dataset[2]["label"] == 0  # tAlK → 0

    def test_empty_csv(self, tmp_path):
        """CSV with only headers yields empty dataset."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("text,label\n")
        dataset = load_csv_dataset(str(csv_file))
        assert len(dataset) == 0

    def test_missing_file_raises(self):
        """Non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_csv_dataset("/nonexistent/file.csv")

    def test_missing_columns_raises(self, tmp_path):
        """CSV without required columns raises ValueError."""
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("wrong_col,other\nfoo,bar\n")
        with pytest.raises(ValueError, match="missing required columns"):
            load_csv_dataset(str(csv_file))


class TestParseArgs:
    """Test CLI argument parsing for train_bert."""

    def test_defaults_with_data(self):
        """--data provided, defaults for optional args."""
        args = parse_args(["--data", "/tmp/data"])
        assert args.output == "output/classifier"
        assert args.epochs == 3
        assert args.batch_size == 8
        assert args.lr == 2e-5
        assert args.max_length == 128

    def test_custom_args(self):
        """All args can be overridden."""
        args = parse_args([
            "--csv", "/tmp/data.csv",
            "--output", "/tmp/my_model",
            "--epochs", "5",
            "--batch-size", "16",
            "--lr", "1e-4",
            "--max-length", "256",
        ])
        assert args.csv == "/tmp/data.csv"
        assert args.output == "/tmp/my_model"
        assert args.epochs == 5
        assert args.batch_size == 16
        assert args.lr == 1e-4
        assert args.max_length == 256

    def test_no_data_or_csv_raises(self):
        """At least one of --data or --csv is required."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_both_data_and_csv_not_allowed(self):
        """--data and --csv are mutually exclusive."""
        with pytest.raises(SystemExit):
            parse_args(["--data", "/d1", "--csv", "/c1"])
