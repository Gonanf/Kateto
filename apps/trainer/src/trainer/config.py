"""
Configuration models for the trainer fine-tuning pipeline.
Uses Pydantic for validation and YAML for serialization.
"""

from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, Field
import yaml


class DatasetConfig(BaseModel):
    """Configuration for a training dataset."""

    name: str
    sources: list[str]  # Keys into data/raw/ directories
    format: Literal["chatml", "alpaca", "csv_classification", "json_input_output"] = (
        "chatml"
    )
    train_split: float = 0.8
    val_split: float = 0.2
    dedup_keys: list[str] = ["text", "output"]  # Fields to deduplicate on
    max_samples: Optional[int] = None
    max_seq_length: int = 512


class ModelConfig(BaseModel):
    """Configuration for a fine-tuned model."""

    name: str
    role: str  # talker, thinker, kingrouter, po_desc, po_pbi, po_dod, po_sprint, po_tasks, classifier
    base_model: str = "unsloth/Qwen3.5-0.8B"
    family: Literal["qwen3.5", "bert"] = "qwen3.5"

    # LoRA parameters
    lora_r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.0
    target_modules: list[str] = Field(
        default_factory=lambda: [
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ]
    )
    use_gradient_checkpointing: bool = True

    # Training parameters
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-4
    warmup_steps: int = 10
    logging_steps: int = 10
    save_steps: int = 500
    eval_steps: int = 100
    max_seq_length: int = 512
    optim: str = "adamw_8bit"

    # Quantization (for export)
    quant_method: Literal["q4_k_m", "q8_0", "f16"] = "q4_k_m"

    # Dataset sources (names referencing DatasetConfig)
    dataset_name: str = ""

    # Deployment / export naming
    llama_cpp_model_name: Optional[str] = None

    # BERT-specific (for classifier)
    bert_num_labels: int = 2
    bert_id2label: Optional[dict] = None
    bert_label2id: Optional[dict] = None


class TrainingRun(BaseModel):
    """Represents a complete training run with artifacts."""

    model_name: str
    dataset_name: str
    output_dir: Path
    base_model: str
    lora_adapters_path: Optional[Path] = None
    merged_model_path: Optional[Path] = None
    gguf_path: Optional[Path] = None
    llama_cpp_model_name: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: Literal["planned", "training", "converting", "deployed", "failed"] = (
        "planned"
    )
    metrics: dict = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    """Top-level pipeline configuration."""

    models: dict[str, ModelConfig]
    datasets: dict[str, DatasetConfig]
    runs: dict[str, TrainingRun] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: Path) -> "PipelineConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: Path):
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


# Factory with defaults for all 9 model types


def create_default_config() -> PipelineConfig:
    """Create the default pipeline configuration with all 9 model types."""
    models = {
        "talker": ModelConfig(
            name="talker",
            role="talker",
            dataset_name="talker_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-talker-qwen3.5-0.8b",
        ),
        "thinker": ModelConfig(
            name="thinker",
            role="thinker",
            dataset_name="thinker_data",
            num_train_epochs=5,
            learning_rate=1e-4,
            llama_cpp_model_name="trainer-thinker-qwen3.5-0.8b",
        ),
        "kingrouter": ModelConfig(
            name="kingrouter",
            role="kingrouter",
            dataset_name="kingrouter_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-kingrouter-qwen3.5-0.8b",
        ),
        "po_desc": ModelConfig(
            name="po_desc",
            role="po_desc",
            dataset_name="po_desc_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-po-desc-qwen3.5-0.8b",
        ),
        "po_pbi": ModelConfig(
            name="po_pbi",
            role="po_pbi",
            dataset_name="po_pbi_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-po-pbi-qwen3.5-0.8b",
        ),
        "po_dod": ModelConfig(
            name="po_dod",
            role="po_dod",
            dataset_name="po_dod_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-po-dod-qwen3.5-0.8b",
        ),
        "po_sprint": ModelConfig(
            name="po_sprint",
            role="po_sprint",
            dataset_name="po_sprint_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-po-sprint-qwen3.5-0.8b",
        ),
        "po_tasks": ModelConfig(
            name="po_tasks",
            role="po_tasks",
            dataset_name="po_tasks_data",
            num_train_epochs=3,
            llama_cpp_model_name="trainer-po-tasks-qwen3.5-0.8b",
        ),
        "classifier": ModelConfig(
            name="classifier",
            role="classifier",
            family="bert",
            dataset_name="classifier_data",
            base_model="distilbert-base-uncased",
            num_train_epochs=3,
            per_device_train_batch_size=8,
            bert_num_labels=2,
            bert_id2label={0: "talk", 1: "think"},
            bert_label2id={"talk": 0, "think": 1},
            llama_cpp_model_name="",  # BERT doesn't use llama.cpp
        ),
    }

    datasets = {
        "talker_data": DatasetConfig(
            name="talker_data",
            sources=["convos", "blogs", "cv", "training"],
            format="chatml",
        ),
        "thinker_data": DatasetConfig(
            name="thinker_data",
            sources=["xavier_quotes"],
            format="chatml",
            max_samples=500,
        ),
        "classifier_data": DatasetConfig(
            name="classifier_data",
            sources=["classifier_csv", "classifier_history"],
            format="csv_classification",
            max_seq_length=128,
        ),
        "kingrouter_data": DatasetConfig(
            name="kingrouter_data",
            sources=["classifier_csv", "convos", "synthetic_routing"],
            format="chatml",
        ),
        "po_desc_data": DatasetConfig(
            name="po_desc_data",
            sources=["synthetic_po_desc"],
            format="chatml",
        ),
        "po_pbi_data": DatasetConfig(
            name="po_pbi_data",
            sources=["synthetic_po_pbi"],
            format="chatml",
        ),
        "po_dod_data": DatasetConfig(
            name="po_dod_data",
            sources=["synthetic_po_dod"],
            format="chatml",
        ),
        "po_sprint_data": DatasetConfig(
            name="po_sprint_data",
            sources=["synthetic_po_sprint"],
            format="chatml",
        ),
        "po_tasks_data": DatasetConfig(
            name="po_tasks_data",
            sources=["synthetic_po_tasks"],
            format="chatml",
        ),
    }

    return PipelineConfig(models=models, datasets=datasets)
