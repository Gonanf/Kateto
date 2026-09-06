"""
CLI: python -m kateto.tools.dataset_filter --input hermes.db --output dataset.jsonl --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("dataset_filter")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kateto.tools.dataset_filter",
        description="DRAFT dataset_filter — filtra hermes.db y genera 50/50 humano/sintético argento",
    )
    p.add_argument("--input", dest="input", required=True, help="hermes.db | .jsonl | .json | .txt")
    p.add_argument("--output", dest="output", required=True, help="dataset.jsonl de salida")
    p.add_argument("--dry-run", action="store_true", help="no llama a LLM ni escribe archivo, solo stats")
    p.add_argument("--limit", type=int, default=None, help="máx pares Q/A de salida")
    p.add_argument("--batch-size", type=int, default=32, help="batch para classifier")
    p.add_argument("--onnx-model-path", default=None, help="path a model.onnx o repo HF (default: Qdrant/all-MiniLM-L6-v2-onnx)")
    p.add_argument("--openai-model", default=None, help="model para generación (env MODEL_NAME / OPENAI_MODEL)")
    p.add_argument("--openai-base-url", default=None, help="base_url OpenAI-compatible (env OPENAI_BASE_URL)")
    p.add_argument("--max-chars", type=int, default=800, help="máx chars por chunk tras split")
    p.add_argument("--no-ai-filter", action="store_true", help="desactiva filtro IA")
    p.add_argument("--no-secrets-filter", action="store_true", help="desactiva filtro de secrets (NO recomendado)")
    p.add_argument("--mode", default=None, choices=["argento", "referencias"],
                   help="modo generación (env DATASET_MODE, default argento)")
    p.add_argument("--no-generate", action="store_true", help="no genera lado faltante (solo clasifica+Filtra)")
    p.add_argument("--concurrency", type=int, default=4, help="requests concurrentes al LLM")
    p.add_argument("--no-vulkan", action="store_true", help="fuerza CPU aunque Vulkan esté disponible")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Validación CLI equivalente a hermes diagnostics: no tocar voces/config existente — solo draft
    from .classifier import MmBertQAClassifier
    from .pipeline import run_pipeline

    onnx_path = args.onnx_model_path or os.getenv("MMBERT_ONNX_PATH") or os.getenv("ONNX_MODEL_PATH")
    clf = MmBertQAClassifier(onnx_path=onnx_path, use_vulkan=not args.no_vulkan)
    if clf.is_onnx:
        log.info("classifier: ONNX activo (%s)", clf.session.get_providers() if clf.session else "?")
    else:
        log.warning("classifier: modo heurístico (sin ONNX) — para Vulkan: pip install onnxruntime tokenizers huggingface-hub y tener model.onnx")

    dataset_mode = args.mode or os.getenv("DATASET_MODE", "argento")
    if dataset_mode not in ("argento", "referencias"):
        parser.error(f"--mode debe ser argento|referencias, no {dataset_mode!r}")

    try:
        stats = asyncio.run(
            run_pipeline(
                input_path=Path(args.input),
                output_path=Path(args.output),
                classifier=clf,
                limit=args.limit,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                filter_ai=not args.no_ai_filter,
                filter_secrets=not args.no_secrets_filter,
                dataset_mode=dataset_mode,  # type: ignore[arg-type] # validado arriba
                generate_missing=not args.no_generate,
                max_chars=args.max_chars,
                openai_model=args.openai_model,
                openai_base_url=args.openai_base_url,
                concurrency=args.concurrency,
            )
        )
    except FileNotFoundError as e:
        log.error("input no encontrado: %s", e)
        sys.exit(2)
    except Exception as e:
        log.exception("pipeline falló: %s", e)
        sys.exit(1)

    log.info("stats: %s", stats)
    # resumen humano
    print(f"\nDone. input={stats['input_texts']} chunks={stats['chunks']} kept={stats['kept_after_ai']} "
          f"dropped_secrets={stats['dropped_secrets']} dropped_ai={stats['dropped_ai']} pairs={stats['pairs']} dry_run={stats['dry_run']}")


if __name__ == "__main__":
    main()
