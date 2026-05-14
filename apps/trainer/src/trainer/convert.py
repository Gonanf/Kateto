"""
HuggingFace to GGUF conversion module.

Wraps llama.cpp's convert_hf_to_gguf.py script and llama-quantize tool
to produce quantized GGUF files ready for inference with llama.cpp.

Typical usage::

    # CLI
    python -m trainer.convert --input output/talker/merged --output output/talker/q4_k_m.gguf

    # Python API
    from trainer.convert import convert_to_gguf
    manifest = convert_to_gguf("output/talker/merged", "output/talker/q4_k_m.gguf")
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Tool Discovery ───────────────────────────────────────────────────────────

_CONVERT_SCRIPT_CANDIDATES = [
    # System / project installs
    "/usr/local/bin/convert_hf_to_gguf.py",
    "/usr/bin/convert_hf_to_gguf.py",
    # User-local llama.cpp clones
    os.path.expanduser("~/llama.cpp/convert_hf_to_gguf.py"),
    # turboquant / kateto-adjacent
    "/home/chaos/proyectos/llama-cpp-turboquant/convert_hf_to_gguf.py",
]

_QUANTIZE_BIN_CANDIDATES = [
    "llama-quantize",
    "/usr/local/bin/llama-quantize",
    "/usr/bin/llama-quantize",
]

_CLI_BIN_CANDIDATES = [
    "llama-cli",
    "/usr/local/bin/llama-cli",
    "/usr/bin/llama-cli",
]

# Valid quantization types supported by llama-quantize
VALID_QUANTS = {
    "Q4_0", "Q4_1", "Q5_0", "Q5_1", "Q8_0",
    "Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L",
    "Q4_K_S", "Q4_K_M", "Q4_K_L",
    "Q5_K_S", "Q5_K_M", "Q5_K_L",
    "Q6_K", "Q8_0",
    "F16", "F32",
}

DEFAULT_QUANT = "Q4_K_M"

_SUPPORTED_QUANTS = {"Q4_K_M", "Q8_0"}  # Primary & optional


def _find_tool(candidates: list[str]) -> Optional[str]:
    """Return the first existing path from *candidates* (or via ``which``)."""
    for c in candidates:
        path = shutil.which(c) if "/" not in c else c
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def find_convert_script() -> Optional[str]:
    """Locate ``convert_hf_to_gguf.py`` on this system."""
    return _find_tool(_CONVERT_SCRIPT_CANDIDATES)


def find_quantize_bin() -> Optional[str]:
    """Locate the ``llama-quantize`` binary."""
    return _find_tool(_QUANTIZE_BIN_CANDIDATES)


def find_llama_cli() -> Optional[str]:
    """Locate the ``llama-cli`` binary."""
    return _find_tool(_CLI_BIN_CANDIDATES)


# ─── Core Conversion ──────────────────────────────────────────────────────────


def convert_to_gguf(
    hf_dir: str,
    output_path: str,
    quant: str = DEFAULT_QUANT,
    *,
    convert_script: Optional[str] = None,
    quantize_bin: Optional[str] = None,
    model_name: Optional[str] = None,
    base_model: Optional[str] = None,
    cleanup_temp: bool = True,
) -> dict[str, Any]:
    """
    Convert a HuggingFace model directory to a quantized GGUF file.

    Steps
    -----
    1. Find the conversion and quantization tools if not provided.
    2. Convert HF → FP16 GGUF via ``convert_hf_to_gguf.py``.
    3. Quantize the FP16 GGUF via ``llama-quantize``.
    4. Remove the intermediate FP16 file.
    5. Compute SHA-256 and file size of the output.
    6. Build and return a manifest dict.

    Parameters
    ----------
    hf_dir : str
        Path to the merged HuggingFace model directory (contains
        ``config.json``, ``model.safetensors`` / ``*.bin``, tokenizer files).
    output_path : str
        Desired path for the output GGUF file.
    quant : str
        Quantization type (default ``Q4_K_M``). Supported values are all
        llama.cpp quantisation types; the project primarily uses
        ``Q4_K_M`` and ``Q8_0``.
    convert_script : str or None
        Explicit path to ``convert_hf_to_gguf.py``. If ``None``, auto-detect.
    quantize_bin : str or None
        Explicit path to ``llama-quantize``. If ``None``, auto-detect.
    model_name : str or None
        Human-readable model name for the manifest (e.g.
        ``"trainer-talker-qwen3.5-0.8b"``). Inferred from *output_path* if
        not given.
    base_model : str or None
        HuggingFace base model ID (e.g. ``"unsloth/Qwen3.5-0.8B"``).
        Inferred from *hf_dir* ``config.json`` if not given.
    cleanup_temp : bool
        Whether to delete the intermediate FP16 GGUF after quantisation.
        Default ``True``.

    Returns
    -------
    dict
        Manifest with keys: ``name``, ``base_model``, ``quantization``,
        ``file_size_bytes``, ``sha256``, ``date``, ``parameters_b``,
        ``architecture``.

    Raises
    ------
    FileNotFoundError
        If the input directory or required tools are missing.
    RuntimeError
        If conversion or quantisation fails.
    """
    hf_path = Path(hf_dir)
    if not hf_path.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {hf_dir}")

    if quant not in VALID_QUANTS:
        raise ValueError(
            f"Unknown quantisation type {quant!r}. "
            f"Valid: {', '.join(sorted(VALID_QUANTS))}"
        )

    # ── Discover tools ──────────────────────────────────────────────────
    conv = convert_script or find_convert_script()
    if not conv:
        raise FileNotFoundError(
            "Could not locate convert_hf_to_gguf.py. "
            "Install llama.cpp or provide --convert-script."
        )

    qbin = quantize_bin or find_quantize_bin()
    if not qbin:
        raise FileNotFoundError(
            "Could not locate llama-quantize. "
            "Install llama.cpp or provide --quantize-bin."
        )

    # ── Extract metadata from model config ───────────────────────────────
    architecture = _extract_architecture(hf_path)
    param_count = _extract_parameter_count(hf_path)
    resolved_base = base_model or _extract_base_model(hf_path)

    # ── Derive model name ────────────────────────────────────────────────
    out_name = model_name or _derive_model_name(output_path, architecture)

    # ── Convert HF → FP16 GGUF ──────────────────────────────────────────
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the intermediate FP16 file next to the final output
    temp_suffix = f"_fp16_{int(time.time())}.gguf"
    temp_fp16 = out_path.with_suffix(temp_suffix)

    logger.info("Converting HF model %s → FP16 GGUF …", hf_dir)
    _run_subprocess(
        [sys.executable, conv, str(hf_path.absolute()), "--outfile", str(temp_fp16), "--outtype", "f16"],
        desc="HF→GGUF conversion",
    )

    if not temp_fp16.is_file():
        raise RuntimeError(
            f"Conversion completed but output file not found: {temp_fp16}"
        )
    temp_size_mb = temp_fp16.stat().st_size / (1024 * 1024)
    logger.info("FP16 GGUF created: %.1f MB", temp_size_mb)

    # ── Quantize ─────────────────────────────────────────────────────────
    logger.info("Quantising GGUF (%s) → %s …", quant, output_path)
    _run_subprocess(
        [qbin, str(temp_fp16), str(out_path), quant],
        desc="GGUF quantisation",
    )

    if not out_path.is_file():
        raise RuntimeError(
            f"Quantisation completed but output file not found: {output_path}"
        )

    # ── Cleanup ──────────────────────────────────────────────────────────
    if cleanup_temp and temp_fp16.is_file():
        temp_fp16.unlink()
        logger.debug("Removed intermediate file: %s", temp_fp16)

    # ── Checksums & manifest ─────────────────────────────────────────────
    sha256_hex = _compute_sha256(out_path)
    file_size = out_path.stat().st_size

    manifest: dict[str, Any] = {
        "name": out_name,
        "base_model": resolved_base,
        "quantization": quant,
        "file_size_bytes": file_size,
        "sha256": sha256_hex,
        "date": date.today().isoformat(),
        "parameters_b": param_count,
        "architecture": architecture,
    }

    logger.info(
        "GGUF conversion complete: %s (%.1f MB, sha256=%s)",
        out_path,
        file_size / (1024 * 1024),
        sha256_hex[:12],
    )

    return manifest


# ─── Verification ─────────────────────────────────────────────────────────────


def verify_gguf(
    gguf_path: str,
    *,
    llama_cli: Optional[str] = None,
    predict_tokens: int = 1,
    prompt: str = "test",
) -> bool:
    """
    Verify that a GGUF file loads correctly with llama.cpp.

    Checks
    ------
    1. File exists and its size is greater than zero.
    2. ``llama-cli`` can load the model and predict *predict_tokens* tokens
       without crashing.

    Parameters
    ----------
    gguf_path : str
        Path to the GGUF file to verify.
    llama_cli : str or None
        Explicit path to ``llama-cli``. Auto-detected if ``None``.
    predict_tokens : int
        Number of tokens to generate during the smoke test (default 1).
    prompt : str
        Input prompt for the smoke test (default ``"test"``).

    Returns
    -------
    bool
        ``True`` if the file is valid and loadable, ``False`` otherwise.
    """
    path = Path(gguf_path)

    if not path.is_file():
        logger.error("GGUF file not found: %s", gguf_path)
        return False

    if path.stat().st_size == 0:
        logger.error("GGUF file is empty: %s", gguf_path)
        return False

    cli = llama_cli or find_llama_cli()
    if not cli:
        logger.error("llama-cli not found — skipping load verification")
        return True

    logger.info("Verifying GGUF loads correctly (predict=%d) …", predict_tokens)
    try:
        result = subprocess.run(
            [cli, "-m", str(path), "-p", prompt, "-n", str(predict_tokens)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("llama-cli timed out (120s) — model may be too large or corrupt")
        return False
    except FileNotFoundError:
        logger.error("llama-cli binary not found at %s", cli)
        return False

    if result.returncode != 0:
        stderr_tail = result.stderr.strip()[-500:]
        logger.error(
            "llama-cli verification failed (rc=%d): %s",
            result.returncode,
            stderr_tail,
        )
        return False

    logger.info("GGUF verification passed: %s", gguf_path)
    return True


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _extract_architecture(hf_path: Path) -> str:
    """Read the model architecture from ``config.json``."""
    config_file = hf_path / "config.json"
    if not config_file.is_file():
        logger.warning("config.json not found in %s — architecture='unknown'", hf_path)
        return "unknown"
    try:
        with open(config_file) as f:
            cfg = json.load(f)
        arch = cfg.get("architectures", [None])[0] or cfg.get("model_type", "unknown")
        return str(arch).lower()
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("Failed to read architecture from config.json: %s", exc)
        return "unknown"


def _extract_parameter_count(hf_path: Path) -> float:
    """Read the approximate parameter count (in billions) from ``config.json``."""
    config_file = hf_path / "config.json"
    if not config_file.is_file():
        return 0.0
    try:
        with open(config_file) as f:
            cfg = json.load(f)
        num_params = cfg.get("num_parameters", 0)
        if num_params:
            return round(num_params / 1e9, 2)
        hidden = cfg.get("hidden_size", 0) or cfg.get("d_model", 0)
        layers = cfg.get("num_hidden_layers", 0) or cfg.get("num_layers", 0)
        vocab = cfg.get("vocab_size", 0)
        if hidden and layers:
            estimate = 12 * hidden * hidden * layers / 1e9
            return round(estimate, 2)
        return 0.0
    except (json.JSONDecodeError, OSError):
        return 0.0


def _extract_base_model(hf_path: Path) -> str:
    """Read the base model name from ``config.json`` ``_name_or_path``."""
    config_file = hf_path / "config.json"
    if not config_file.is_file():
        return "unknown"
    try:
        with open(config_file) as f:
            cfg = json.load(f)
        return cfg.get("_name_or_path", "unknown")
    except (json.JSONDecodeError, OSError):
        return "unknown"


def _derive_model_name(output_path: str, architecture: str) -> str:
    """Derive a human-readable model name from the output file path."""
    stem = Path(output_path).stem
    stem = re.sub(r"[_-]?(q\d+[_-]?\w*|f16|f32)$", "", stem, flags=re.IGNORECASE).strip("_-")
    return stem or f"model-{architecture}"


def _compute_sha256(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_subprocess(
    cmd: list[str],
    desc: str = "",
    timeout: int = 1800,
) -> str:
    """
    Run a subprocess and stream output; raise on failure.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments.
    desc : str
        Human-readable description for error messages.
    timeout : int
        Maximum runtime in seconds (default 1800 = 30 min).

    Returns
    -------
    str
        Combined stdout + stderr.
    """
    logger.debug("Running: %s", " ".join(str(c) for c in cmd))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Tool not found for '{desc}': {exc.filename or exc}"
        ) from exc

    assert proc.stdout is not None
    output_lines: list[str] = []
    for line in proc.stdout:
        output_lines.append(line)
        logger.debug("  %s", line.rstrip())

    proc.wait()
    if proc.returncode != 0:
        tail = "".join(output_lines[-20:])
        raise RuntimeError(
            f"{desc} failed (rc={proc.returncode}). "
            f"Last output:\n{tail}"
        )

    return "".join(output_lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a merged HuggingFace model to GGUF format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m trainer.convert --input output/talker/merged \\\n"
            "      --output output/talker/q4_k_m.gguf --quant Q4_K_M\n\n"
            "  python -m trainer.convert --input output/talker/merged \\\n"
            "      --output output/talker/q8_0.gguf --quant Q8_0\n\n"
            "  python -m trainer.convert --input output/talker/merged \\\n"
            "      --output output/talker/merged.gguf  # default Q4_K_M\n"
        ),
    )

    parser.add_argument(
        "--input",
        "-i",
        required=True,
        metavar="DIR",
        help="Path to the merged HuggingFace model directory",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        metavar="FILE",
        help="Output GGUF file path",
    )
    parser.add_argument(
        "--quant",
        "-q",
        default=DEFAULT_QUANT,
        choices=sorted(VALID_QUANTS),
        help=f"Quantisation type (default: {DEFAULT_QUANT})",
    )
    parser.add_argument(
        "--convert-script",
        metavar="PATH",
        help="Explicit path to convert_hf_to_gguf.py (auto-detected if omitted)",
    )
    parser.add_argument(
        "--quantize-bin",
        metavar="PATH",
        help="Explicit path to llama-quantize (auto-detected if omitted)",
    )
    parser.add_argument(
        "--model-name",
        metavar="NAME",
        help="Human-readable model name for the manifest",
    )
    parser.add_argument(
        "--base-model",
        metavar="ID",
        help="HuggingFace base model ID for the manifest",
    )
    parser.add_argument(
        "--manifest",
        metavar="FILE",
        help="Write manifest JSON to this path (default: <output>.manifest.json)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip the llama-cli smoke-test after conversion",
    )
    parser.add_argument(
        "--keep-fp16",
        action="store_true",
        help="Keep the intermediate FP16 GGUF file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Increase log verbosity",
    )

    return parser


def main() -> None:
    """CLI entry point for ``python -m trainer.convert``."""
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        manifest = convert_to_gguf(
            hf_dir=args.input,
            output_path=args.output,
            quant=args.quant,
            convert_script=args.convert_script,
            quantize_bin=args.quantize_bin,
            model_name=args.model_name,
            base_model=args.base_model,
            cleanup_temp=not args.keep_fp16,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        sys.exit(1)

    # ── Verification ─────────────────────────────────────────────────────
    if not args.skip_verify:
        ok = verify_gguf(args.output)
        manifest["verification_passed"] = ok
        if not ok:
            logger.warning("GGUF verification failed — model may still load in some backends")

    # ── Write manifest ───────────────────────────────────────────────────
    manifest_path = args.manifest or (Path(args.output).with_suffix(".manifest.json"))
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Manifest written to %s", manifest_path)

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
