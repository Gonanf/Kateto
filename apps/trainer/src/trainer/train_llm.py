#!/usr/bin/env python3
"""
bf16 LoRA fine-tuning pipeline for Qwen3.5-0.8B using Unsloth.

Trains a Qwen3.5-0.8B model with LoRA adapters, saves both the adapters
and a merged 16-bit model. Uses bf16 precision (not QLoRA 4-bit).

Usage:
    python -m trainer.train_llm --model unsloth/Qwen3.5-0.8B \\
        --dataset data/processed/talker --output-dir output/talker --epochs 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from trainer.config import ModelConfig

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse and return CLI arguments."""
    parser = argparse.ArgumentParser(
        description="bf16 LoRA fine-tuning for Qwen3.5-0.8B via Unsloth"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="unsloth/Qwen3.5-0.8B",
        help="Base model name (default: unsloth/Qwen3.5-0.8B)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        required=True,
        help="Path to processed HuggingFace Dataset directory",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Output directory for LoRA adapters, merged model, and logs",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)",
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=2e-4,
        help="Learning rate (default: 2e-4)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Per-device training batch size (default: 1)",
    )
    parser.add_argument(
        "--grad-accum",
        type=int,
        default=8,
        help="Gradient accumulation steps (default: 8)",
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=512,
        help="Maximum sequence length (default: 512)",
    )
    parser.add_argument(
        "--lora-r",
        type=int,
        default=8,
        help="LoRA rank (default: 8)",
    )
    parser.add_argument(
        "--lora-alpha",
        type=int,
        default=16,
        help="LoRA alpha (default: 16)",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="Path to checkpoint directory to resume from",
    )
    return parser.parse_args(argv)


def check_environment() -> None:
    """Verify GPU availability and warn if ROCm/CUDA is not available.

    Logs total VRAM per device and warns if below the ~3 GB needed for
    Qwen3.5-0.8B bf16 LoRA training.
    """
    import torch

    if not torch.cuda.is_available():
        logger.warning(
            "CUDA/ROCm is NOT available. Training will fall back to CPU "
            "(extremely slow)."
        )
        return

    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        vram_gb = props.total_memory / (1024**3)
        logger.info("GPU %d: %s — %.1f GB VRAM", i, props.name, vram_gb)
        if vram_gb < 4.0:
            logger.warning(
                "GPU %d has only %.1f GB VRAM. Qwen3.5-0.8B bf16 LoRA "
                "needs ~3 GB — OOM may occur with long sequences.",
                i,
                vram_gb,
            )


def build_config(args: argparse.Namespace) -> ModelConfig:
    return ModelConfig(
        name=Path(args.output_dir).name,
        role="",
        base_model=args.model,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        max_seq_length=args.max_seq_length,
    )


def _load_dataset(dataset_path: str) -> tuple:
    """Load a HuggingFace Dataset from disk, returning (train, val).

    Handles both ``Dataset`` and ``DatasetDict`` formats.  Validation is
    optional — returns ``None`` if no validation split is found.
    Returns ``(train_dataset, val_dataset_or_None)``.
    """
    from datasets import load_from_disk, Dataset, DatasetDict

    raw = load_from_disk(dataset_path)

    if isinstance(raw, DatasetDict):
        train_ds = raw.get("train")
        if train_ds is None:
            train_ds = list(raw.values())[0]
            logger.warning(
                "No 'train' split found; using first available split (%s).",
                list(raw.keys())[0],
            )
        val_ds = raw.get("validation") or raw.get("eval")
        logger.info(
            "DatasetDict loaded: train=%d rows, val=%s rows",
            len(train_ds),
            len(val_ds) if val_ds is not None else "N/A",
        )
    else:
        train_ds = raw
        val_ds = None
        logger.info("Dataset loaded: %d rows (no validation split)", len(train_ds))

    required = {"text"}
    missing = required - set(train_ds.column_names)
    if missing:
        raise ValueError(
            f"Dataset is missing required column(s): {missing}. "
            f"Available columns: {train_ds.column_names}. "
            "Ensure the dataset was prepared by trainer.prepare()."
        )

    return train_ds, val_ds


def train(
    config: ModelConfig,
    dataset_path: str,
    output_dir: str,
    resume_from: Optional[str] = None,
) -> dict:
    """Run the full training pipeline.

    Parameters
    ----------
    config : ModelConfig
        Model identity and hyper-parameters.
    dataset_path : str
        Path to the processed HuggingFace Dataset directory
        (``datasets.load_from_disk`` format).
    output_dir : str
        Output directory for LoRA adapters, merged model, and training logs.
    resume_from : str, optional
        Path to a checkpoint directory to resume training from.

    Returns
    -------
    dict
        Training metrics (loss, runtime, samples).
    """
    import torch
    from trl import SFTConfig, SFTTrainer  # pyright: ignore[reportPrivateImportUsage]
    from unsloth import FastLanguageModel, is_bfloat16_supported

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    use_bf16 = is_bfloat16_supported()

    # ── 1. Load model ─────────────────────────────────────────────────────
    logger.info(
        "Loading model: %s (dtype=%s, load_in_4bit=False)",
        config.base_model,
        "bf16" if use_bf16 else "fp16",
    )
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=config.base_model,
            max_seq_length=config.max_seq_length,
            dtype=torch.bfloat16 if use_bf16 else torch.float16,
            load_in_4bit=False,  # CRITICAL: Unsloth warns against QLoRA for Qwen3.5
        )
    except torch.cuda.OutOfMemoryError:
        logger.error(
            "CUDA OOM while loading model '%s'. Try a smaller model or "
            "reduce --max-seq-length.",
            config.base_model,
        )
        raise
    except Exception as exc:
        logger.error("Failed to load model '%s': %s", config.base_model, exc)
        raise

    # ── 2. Apply LoRA adapters ────────────────────────────────────────────
    logger.info(
        "Applying LoRA: r=%d, alpha=%d, targets=%s",
        config.lora_r,
        config.lora_alpha,
        config.target_modules,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=config.lora_r,
        lora_alpha=config.lora_alpha,
        target_modules=config.target_modules,
        use_gradient_checkpointing="unsloth",  # type: ignore[arg-type]
        random_state=42,
    )

    # ── 3. Load dataset ───────────────────────────────────────────────────
    train_dataset, eval_dataset = _load_dataset(dataset_path)
    logger.info("Training samples: %d", len(train_dataset))
    if eval_dataset is not None:
        logger.info("Validation samples: %d", len(eval_dataset))

    # ── 4. Training arguments ─────────────────────────────────────────────
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=config.num_train_epochs,
        per_device_train_batch_size=config.per_device_train_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        warmup_steps=config.warmup_steps,
        logging_steps=config.logging_steps,
        save_steps=config.save_steps,
        eval_strategy="steps" if eval_dataset is not None else "no",
        eval_steps=config.eval_steps if eval_dataset is not None else None,
        optim=config.optim,
        fp16=not use_bf16,
        bf16=use_bf16,
        report_to="none",
        dataloader_num_workers=0,  # ROCm stability
        ddp_find_unused_parameters=False,
        save_total_limit=3,
        load_best_model_at_end=False,
        seed=42,
        dataset_text_field="text",
        max_length=config.max_seq_length,
        packing=False,
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
    )

    # ── 5. Train ──────────────────────────────────────────────────────────
    logger.info("Starting training (epochs=%d)...", config.num_train_epochs)
    try:
        train_result = trainer.train(resume_from_checkpoint=resume_from)
    except torch.cuda.OutOfMemoryError:
        logger.error(
            "CUDA OOM during training. Try: smaller --max-seq-length, "
            "larger --grad-accum, or disable gradient_checkpointing."
        )
        raise
    except Exception as exc:
        logger.error("Training failed: %s", exc)
        raise

    # ── 6. Save LoRA adapters ─────────────────────────────────────────────
    lora_path = output_path / "lora"
    logger.info("Saving LoRA adapters to: %s", lora_path)
    trainer.model.save_pretrained(str(lora_path))  # type: ignore
    tokenizer.save_pretrained(str(lora_path))

    # ── 7. Merge LoRA into base model and save 16-bit ─────────────────────
    merged_path = output_path / "merged"
    logger.info("Merging LoRA into base model → %s", merged_path)
    model.save_pretrained_merged(str(merged_path), tokenizer, save_method="merged_16bit")

    # ── 8. Save training log ──────────────────────────────────────────────
    metrics: dict = {
        "base_model": config.base_model,
        "lora_r": config.lora_r,
        "lora_alpha": config.lora_alpha,
        "num_train_epochs": config.num_train_epochs,
        "per_device_train_batch_size": config.per_device_train_batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "learning_rate": config.learning_rate,
        "max_seq_length": config.max_seq_length,
        "optimizer": config.optim,
        "train_samples": len(train_dataset),
        "train_runtime": train_result.metrics.get("train_runtime", 0),
        "train_loss": train_result.metrics.get("train_loss", None),
        "train_steps_per_second": train_result.metrics.get(
            "train_steps_per_second", None
        ),
    }
    if eval_dataset is not None:
        metrics["eval_samples"] = len(eval_dataset)

    log_path = output_path / "training_log.json"
    with open(log_path, "w") as f:
        json.dump(metrics, f, indent=2)
    logger.info("Training metrics saved to: %s", log_path)

    if hasattr(trainer.state, "log_history") and trainer.state.log_history:
        step_logs = [e for e in trainer.state.log_history if "loss" in e]
        if step_logs:
            steps_path = output_path / "training_steps.json"
            with open(steps_path, "w") as f:
                json.dump(step_logs, f, indent=2)
            logger.info("Per-step loss log saved to: %s", steps_path)

    logger.info("Training complete. All artifacts in: %s", output_dir)
    return metrics


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )


def main(argv: Optional[list[str]] = None) -> None:
    setup_logging()
    args = parse_args(argv)
    check_environment()
    config = build_config(args)

    train(
        config=config,
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        resume_from=args.resume_from,
    )


if __name__ == "__main__":
    main()
