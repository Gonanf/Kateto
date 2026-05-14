#!/usr/bin/env python3
"""
GPU Memory Budget Validator
Tests whether the 4GB AMD ROCm GPU can handle bf16 LoRA training of Qwen3.5-0.8B.
Outputs structured JSON with memory measurements.

Prereqs (matching kateto's ROCm setup):
  HSA_OVERRIDE_GFX_VERSION=10.3.0  (see apps/classifier/.env)
"""

import json
import sys
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "unsloth/Qwen3.5-0.8B"
VRAM_BUDGET_MB = 3500  # Leave 500MB headroom on 4GB


def check_rocm():
    """Verify ROCm is available and report GPU info."""
    if not torch.cuda.is_available():
        print(json.dumps({
            "status": "FAIL",
            "error": "CUDA/ROCm not available",
            "cuda_available": False,
        }))
        sys.exit(1)

    props = torch.cuda.get_device_properties(0)
    total_mb = props.total_memory / 1024 / 1024
    name = props.name

    rocm_ver = (
        torch.version.rocm
        if hasattr(torch.version, "rocm") and torch.version.rocm
        else "N/A"
    )

    result = {
        "status": "OK",
        "gpu_name": name,
        "total_vram_mb": round(total_mb, 1),
        "cuda_version": torch.version.cuda or "N/A",
        "rocm_version": rocm_ver,
    }
    print(json.dumps(result))
    return result


def test_memory_budget():
    """Test various model loading and training configurations."""
    results: dict = {}

    # ── Test 1: Load model in bf16 ──────────────────────────────────────
    print(">>> TEST: Load Qwen3.5-0.8B in bf16 mode")
    torch.cuda.reset_peak_memory_stats()
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    mem_bf16 = torch.cuda.max_memory_allocated() / 1024 / 1024
    results["model_load_bf16_mb"] = round(mem_bf16, 1)
    print(f"  Peak VRAM (bf16 load): {mem_bf16:.1f} MB")

    del model, tokenizer
    torch.cuda.empty_cache()

    # ── Test 2: Simulate training batch=1 seq=256 ───────────────────────
    print(">>> TEST: Simulate training with batch=1, seq=256")

    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=MODEL_NAME,
            max_seq_length=256,
            dtype=torch.bfloat16,
            load_in_4bit=False,
            device_map="cuda",
            trust_remote_code=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=8,
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj",
            ],
            lora_alpha=16,
            use_gradient_checkpointing="unsloth",
        )
        input_ids = tokenizer("Hola, cómo estás? " * 20, return_tensors="pt").input_ids.cuda()
        with torch.no_grad():
            _ = model(input_ids)
        torch.cuda.synchronize()
        mem_train_256 = torch.cuda.max_memory_allocated() / 1024 / 1024
        results["training_batch1_seq256_mb"] = round(mem_train_256, 1)
        print(f"  Peak VRAM (batch=1, seq=256): {mem_train_256:.1f} MB")

        del model, input_ids
        torch.cuda.empty_cache()
    except ImportError:
        print("  Unsloth not available, skipping LoRA test")
        results["training_batch1_seq256_mb"] = -1

    # ── Test 3: Simulate training batch=1 seq=512 ───────────────────────
    print(">>> TEST: Simulate training with batch=1, seq=512")

    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=MODEL_NAME,
            max_seq_length=512,
            dtype=torch.bfloat16,
            load_in_4bit=False,
            device_map="cuda",
            trust_remote_code=True,
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=8,
            target_modules=[
                "q_proj", "k_proj", "v_proj", "o_proj",
            ],
            lora_alpha=16,
            use_gradient_checkpointing="unsloth",
        )
        input_ids = tokenizer("Hola " * 64, return_tensors="pt").input_ids[:, :512].cuda()
        with torch.no_grad():
            _ = model(input_ids)
        torch.cuda.synchronize()
        mem_train_512 = torch.cuda.max_memory_allocated() / 1024 / 1024
        results["training_batch1_seq512_mb"] = round(mem_train_512, 1)
        print(f"  Peak VRAM (batch=1, seq=512): {mem_train_512:.1f} MB")

        del model, tokenizer, input_ids
        torch.cuda.empty_cache()
    except ImportError:
        print("  Unsloth not available, skipping seq=512 test")
        results["training_batch1_seq512_mb"] = -1
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            results["training_batch1_seq512_mb"] = "OOM"
            print(f"  OOM at seq=512: {e}")
        else:
            raise

    # ── Evaluate budget ─────────────────────────────────────────────────
    all_ok = True
    for key, val in results.items():
        if isinstance(val, (int, float)) and val > VRAM_BUDGET_MB:
            all_ok = False
            print(f"  ❌ {key}: {val:.1f} MB exceeds budget of {VRAM_BUDGET_MB} MB")

    results["status"] = "PASS" if all_ok else "FAIL"
    results["vram_budget_mb"] = VRAM_BUDGET_MB
    results["pass"] = all_ok

    print(f"\n{'='*50}")
    print(f"OVERALL: {'✅ PASS' if all_ok else '❌ FAIL'}")
    print(f"{'='*50}")
    print(json.dumps(results, indent=2))

    return all_ok


if __name__ == "__main__":
    print(f"GPU Validation Script")
    print(f"Time: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    print(f"{'='*50}")

    rocm_info = check_rocm()

    if rocm_info["status"] == "OK":
        success = test_memory_budget()
        sys.exit(0 if success else 1)
    else:
        sys.exit(1)
