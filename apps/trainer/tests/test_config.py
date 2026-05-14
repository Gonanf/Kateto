"""Tests for trainer configuration module."""

import pytest
import tempfile
from pathlib import Path
from trainer.config import ModelConfig, DatasetConfig, PipelineConfig, create_default_config


class TestModelConfig:
    def test_default_creation(self):
        config = ModelConfig(name="test", role="talker", dataset_name="test_data")
        assert config.name == "test"
        assert config.base_model == "unsloth/Qwen3.5-0.8B"
        assert config.lora_r == 8

    def test_bert_config(self):
        config = ModelConfig(
            name="classifier",
            role="classifier",
            family="bert",
            base_model="distilbert-base-uncased",
            dataset_name="test",
            bert_num_labels=2,
        )
        assert config.family == "bert"
        assert config.bert_num_labels == 2

    def test_invalid_family(self):
        with pytest.raises(ValueError):
            ModelConfig(
                name="bad",
                role="talker",
                family="invalid_family",  # type: ignore
                dataset_name="test",
            )

    def test_invalid_quant_method(self):
        with pytest.raises(ValueError):
            ModelConfig(
                name="bad",
                role="talker",
                quant_method="invalid_quant",  # type: ignore
                dataset_name="test",
            )


class TestDatasetConfig:
    def test_default_creation(self):
        config = DatasetConfig(name="test", sources=["convos"])
        assert config.train_split == 0.8
        assert config.format == "chatml"

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            DatasetConfig(
                name="bad",
                sources=["test"],
                format="invalid_format",  # type: ignore
            )

    def test_max_seq_length_default(self):
        config = DatasetConfig(name="test", sources=["convos"])
        assert config.max_seq_length == 512

    def test_max_samples_optional(self):
        config = DatasetConfig(name="test", sources=["convos"], max_samples=100)
        assert config.max_samples == 100
        config2 = DatasetConfig(name="test2", sources=["convos"])
        assert config2.max_samples is None


class TestTrainingRun:
    def test_default_status(self):
        from trainer.config import TrainingRun

        run = TrainingRun(
            model_name="talker",
            dataset_name="talker_data",
            output_dir=Path("/tmp/out"),
            base_model="unsloth/Qwen3.5-0.8B",
        )
        assert run.status == "planned"
        assert run.metrics == {}

    def test_invalid_status(self):
        from trainer.config import TrainingRun

        with pytest.raises(ValueError):
            TrainingRun(
                model_name="talker",
                dataset_name="talker_data",
                output_dir=Path("/tmp/out"),
                base_model="unsloth/Qwen3.5-0.8B",
                status="invalid_status",  # type: ignore
            )


class TestPipelineConfig:
    def test_create_default(self):
        config = create_default_config()
        assert len(config.models) == 9  # 9 model types
        assert len(config.datasets) == 9  # 9 dataset types

    def test_default_has_talker(self):
        config = create_default_config()
        assert "talker" in config.models
        assert config.models["talker"].role == "talker"

    def test_default_has_classifier(self):
        config = create_default_config()
        assert "classifier" in config.models
        assert config.models["classifier"].family == "bert"

    def test_yaml_roundtrip(self):
        config = create_default_config()
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            config.to_yaml(Path(f.name))
            loaded = PipelineConfig.from_yaml(Path(f.name))
        assert len(loaded.models) == len(config.models)
        assert loaded.models["talker"].name == "talker"

    def test_yaml_roundtrip_all_fields(self):
        config = create_default_config()
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            config.to_yaml(Path(f.name))
            loaded = PipelineConfig.from_yaml(Path(f.name))
        for model_key in config.models:
            orig = config.models[model_key]
            loaded_m = loaded.models[model_key]
            assert loaded_m.name == orig.name
            assert loaded_m.role == orig.role
            assert loaded_m.base_model == orig.base_model
            assert loaded_m.family == orig.family
            assert loaded_m.lora_r == orig.lora_r
            assert loaded_m.dataset_name == orig.dataset_name
        for ds_key in config.datasets:
            orig = config.datasets[ds_key]
            loaded_ds = loaded.datasets[ds_key]
            assert loaded_ds.name == orig.name
            assert loaded_ds.format == orig.format
            assert loaded_ds.max_seq_length == orig.max_seq_length
