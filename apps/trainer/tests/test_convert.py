"""Tests for convert.py — tool discovery, helpers, and CLI error paths.

All tests are CPU-compatible and do not require a GPU or real model files.
"""

import pytest
import json
import subprocess
import sys
from pathlib import Path
from trainer.convert import (
    find_convert_script,
    find_quantize_bin,
    find_llama_cli,
    _extract_architecture,
    _extract_parameter_count,
    _extract_base_model,
    _derive_model_name,
    _compute_sha256,
    convert_to_gguf,
    verify_gguf,
)


class TestToolDiscovery:
    """System tool path discovery."""

    def test_find_convert_script(self):
        """Should find convert_hf_to_gguf.py on the system."""
        path = find_convert_script()
        assert path is not None, "convert_hf_to_gguf.py not found"
        assert Path(path).exists()

    def test_find_quantize_bin(self):
        """Should find llama-quantize on the system."""
        path = find_quantize_bin()
        assert path is not None, "llama-quantize not found"
        assert Path(path).exists()

    def test_find_llama_cli(self):
        """Should find llama-cli on the system."""
        path = find_llama_cli()
        assert path is not None, "llama-cli not found"
        assert Path(path).exists()


class TestExtractHelpers:
    """Helpers that parse model metadata from config.json."""

    def test_extract_architecture_missing(self, tmp_path):
        """Missing config.json → 'unknown'."""
        arch = _extract_architecture(tmp_path)
        assert arch == "unknown"

    def test_extract_architecture_valid(self, tmp_path):
        """config.json with architectures list."""
        (tmp_path / "config.json").write_text(
            json.dumps({"architectures": ["Qwen2ForCausalLM"]})
        )
        assert _extract_architecture(tmp_path) == "qwen2forcausallm"

    def test_extract_architecture_fallback(self, tmp_path):
        """config.json without architectures but with model_type."""
        (tmp_path / "config.json").write_text(
            json.dumps({"model_type": "bert"})
        )
        assert _extract_architecture(tmp_path) == "bert"

    def test_extract_parameter_count_missing(self, tmp_path):
        """No config.json → 0.0."""
        assert _extract_parameter_count(tmp_path) == 0.0

    def test_extract_parameter_count_exact(self, tmp_path):
        """config.json with num_parameters."""
        (tmp_path / "config.json").write_text(
            json.dumps({"num_parameters": 500_000_000})
        )
        assert _extract_parameter_count(tmp_path) == 0.5

    def test_extract_parameter_count_estimated(self, tmp_path):
        """Estimate from hidden_size × num_hidden_layers."""
        (tmp_path / "config.json").write_text(
            json.dumps({"hidden_size": 768, "num_hidden_layers": 12, "vocab_size": 30522})
        )
        count = _extract_parameter_count(tmp_path)
        assert count > 0.0

    def test_extract_base_model_missing(self, tmp_path):
        """No config.json → 'unknown'."""
        assert _extract_base_model(tmp_path) == "unknown"

    def test_extract_base_model_present(self, tmp_path):
        """config.json with _name_or_path."""
        (tmp_path / "config.json").write_text(
            json.dumps({"_name_or_path": "unsloth/Qwen3.5-0.8B"})
        )
        assert _extract_base_model(tmp_path) == "unsloth/Qwen3.5-0.8B"

    def test_extract_base_model_empty(self, tmp_path):
        """config.json missing _name_or_path → 'unknown'."""
        (tmp_path / "config.json").write_text(json.dumps({}))
        assert _extract_base_model(tmp_path) == "unknown"


class TestDeriveModelName:
    """Model name derivation from output path."""

    def test_strips_quant_suffix(self):
        assert _derive_model_name("output/talker-q4_k_m.gguf", "qwen2") == "talker"

    def test_strips_f16_suffix(self):
        assert _derive_model_name("output/talker-f16.gguf", "qwen2") == "talker"

    def test_strips_f32_suffix(self):
        assert _derive_model_name("output/talker-f32.gguf", "qwen2") == "talker"

    def test_empty_stem_falls_back(self):
        """When stem is empty after stripping, use 'model-{architecture}'."""
        name = _derive_model_name("q4_k_m.gguf", "qwen2")
        assert name == "model-qwen2"

    def test_preserves_plain_name(self):
        """No quant suffix → use stem as-is."""
        assert _derive_model_name("output/my-model.gguf", "qwen2") == "my-model"


class TestComputeSha256:
    """SHA-256 computation helper."""

    def test_known_content(self, tmp_path):
        """SHA-256 of known bytes."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world\n")
        expected = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
        assert _compute_sha256(f) == expected

    def test_empty_file(self, tmp_path):
        """SHA-256 of empty file."""
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert _compute_sha256(f) == expected


class TestCLI:
    """CLI argument parsing and error paths."""

    def test_help_flag(self):
        """--help should print usage and exit 0."""
        result = subprocess.run(
            [sys.executable, "-m", "trainer.convert", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--input" in result.stdout or "--input" in result.stderr
        assert "--output" in result.stdout or "--output" in result.stderr

    def test_missing_input(self):
        """Non-existent input directory should fail."""
        result = subprocess.run(
            [
                sys.executable, "-m", "trainer.convert",
                "--input", "/nonexistent_dir_xyz",
                "--output", "/tmp/test_fail.gguf",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_invalid_quant(self):
        """Invalid quant type should fail."""
        result = subprocess.run(
            [
                sys.executable, "-m", "trainer.convert",
                "--input", "/tmp",
                "--output", "/tmp/test.gguf",
                "--quant", "INVALID_QUANT",
            ],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_convert_to_gguf_nonexistent_input(self):
        """convert_to_gguf raises FileNotFoundError for missing input dir."""
        with pytest.raises(FileNotFoundError):
            convert_to_gguf(
                hf_dir="/nonexistent_hf_dir",
                output_path="/tmp/test_out.gguf",
            )

    def test_convert_to_gguf_invalid_quant(self, tmp_path):
        """convert_to_gguf raises ValueError for unknown quant type."""
        hf_dir = tmp_path / "model"
        hf_dir.mkdir()
        (hf_dir / "config.json").write_text(json.dumps({"model_type": "test"}))
        with pytest.raises(ValueError, match="Unknown quantisation type"):
            convert_to_gguf(
                hf_dir=str(hf_dir),
                output_path="/tmp/test_bad_quant.gguf",
                quant="Q99_Z",
            )

    def test_verify_gguf_missing_file(self):
        """verify_gguf returns False for nonexistent file."""
        assert verify_gguf("/nonexistent.gguf") is False

    def test_verify_gguf_empty_file(self, tmp_path):
        """verify_gguf returns False for empty file."""
        f = tmp_path / "empty.gguf"
        f.write_bytes(b"")
        assert verify_gguf(str(f)) is False
