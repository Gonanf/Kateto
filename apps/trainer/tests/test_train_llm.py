"""Tests for train_llm.py — argument parsing and config building.

GPU-dependent tests are marked @pytest.mark.gpu and are skipped
when running with ``-m "not gpu"``.
"""

import pytest
from pathlib import Path
from trainer.train_llm import parse_args, build_config


class TestParseArgs:
    """Test CLI argument parsing (no GPU required)."""

    def test_default_args(self):
        """Default values for optional args."""
        args = parse_args(["--dataset", "/tmp/test", "--output-dir", "/tmp/out"])
        assert args.model == "unsloth/Qwen3.5-0.8B"
        assert args.epochs == 3
        assert args.batch_size == 1
        assert args.lr == 2e-4
        assert args.grad_accum == 8
        assert args.max_seq_length == 512
        assert args.lora_r == 8
        assert args.lora_alpha == 16
        assert args.resume_from is None

    def test_custom_args(self):
        """All optional args can be overridden."""
        args = parse_args([
            "--model", "test/model",
            "--dataset", "/tmp/test",
            "--output-dir", "/tmp/out",
            "--epochs", "5",
            "--lr", "1e-4",
            "--batch-size", "2",
            "--grad-accum", "4",
            "--max-seq-length", "1024",
            "--lora-r", "16",
            "--lora-alpha", "32",
            "--resume-from", "/tmp/checkpoint",
        ])
        assert args.model == "test/model"
        assert args.epochs == 5
        assert args.lr == 1e-4
        assert args.batch_size == 2
        assert args.grad_accum == 4
        assert args.max_seq_length == 1024
        assert args.lora_r == 16
        assert args.lora_alpha == 32
        assert args.resume_from == "/tmp/checkpoint"

    def test_required_args_missing(self):
        """Missing --dataset or --output-dir should raise SystemExit."""
        with pytest.raises(SystemExit):
            parse_args([])
        with pytest.raises(SystemExit):
            parse_args(["--dataset", "/tmp/test"])
        with pytest.raises(SystemExit):
            parse_args(["--output-dir", "/tmp/out"])

    def test_non_existent_arg_types(self):
        """Invalid types for numeric args should raise SystemExit."""
        with pytest.raises(SystemExit):
            parse_args(["--dataset", "/tmp/test", "--output-dir", "/tmp/out", "--epochs", "not_a_number"])


class TestBuildConfig:
    """Test ModelConfig construction from parsed args."""

    def test_build_config_from_defaults(self):
        """build_config produces a ModelConfig matching the defaults."""
        args = parse_args(["--dataset", "/tmp/test", "--output-dir", "/tmp/out"])
        config = build_config(args)
        assert config.base_model == "unsloth/Qwen3.5-0.8B"
        assert config.lora_r == 8
        assert config.lora_alpha == 16
        assert config.num_train_epochs == 3
        assert config.per_device_train_batch_size == 1
        assert config.gradient_accumulation_steps == 8
        assert config.learning_rate == 2e-4
        assert config.max_seq_length == 512

    def test_build_config_name_from_output_dir(self):
        """The ModelConfig name is derived from output-dir's last path component."""
        args = parse_args(["--dataset", "/tmp/test", "--output-dir", "/tmp/out/my_model"])
        config = build_config(args)
        assert config.name == "my_model"


# ── GPU-dependent tests (skipped with -m "not gpu") ──────────────────────────


@pytest.mark.gpu
def test_check_environment_does_not_crash():
    """check_environment() should run without raising on any hardware."""
    from trainer.train_llm import check_environment
    check_environment()


@pytest.mark.gpu
def test_build_config_with_gpu_defaults():
    """Re-assert build_config under GPU marker (safety net)."""
    from trainer.train_llm import parse_args, build_config
    args = parse_args(["--dataset", "/tmp/test", "--output-dir", "/tmp/gpu_out"])
    config = build_config(args)
    assert config.name == "gpu_out"
