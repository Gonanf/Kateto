"""
llama.cpp/llama-server model deployment module.

Handles copying GGUF files to the model directory, creating/updating
llama-server preset config entries, and validating deployed models
via the OpenAI-compatible API.

Typical usage::

    # CLI — deploy a GGUF
    python -m trainer.deploy --gguf output/talker/q4_k_m.gguf --name trainer-talker-qwen3.5-0.8b

    # CLI — list deployed models
    python -m trainer.deploy --list

    # CLI — validate a model
    python -m trainer.deploy --validate --name trainer-talker-qwen3.5-0.8b

    # CLI — undeploy a model
    python -m trainer.deploy --undeploy --name trainer-talker-qwen3.5-0.8b

    # Python API
    from trainer.deploy import deploy_gguf, list_deployed, validate_model, undeploy_model
    manifest = deploy_gguf("output/talker/q4_k_m.gguf", "trainer-talker-qwen3.5-0.8b")
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Default Paths ────────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/llama/config.ini")
DEFAULT_MODELS_DIR = os.path.expanduser("~/.llama/models")
DEFAULT_API_BASE = "http://localhost:11434/v1"

# Sensible defaults for fine-tuned models (Qwen3.5-0.8B class)
_DEFAULT_CTX_SIZE = 8192
_DEFAULT_TEMPERATURE = 0.6
_DEFAULT_FLASH_ATTN = "on"

# ─── Path Resolution ─────────────────────────────────────────────────────────

def get_config_path() -> str:
    """Return the path to the llama-server config.ini."""
    return DEFAULT_CONFIG_PATH


def get_models_dir() -> str:
    """Return the default models storage directory."""
    return DEFAULT_MODELS_DIR


# ─── Deploy ───────────────────────────────────────────────────────────────────

def deploy_gguf(
    gguf_path: str,
    model_name: str,
    alias: str = "",
    models_dir: str = DEFAULT_MODELS_DIR,
    config_path: str = DEFAULT_CONFIG_PATH,
    api_base: str = DEFAULT_API_BASE,
) -> dict[str, Any]:
    """
    Deploy a GGUF model to the llama.cpp server.

    1. Copy GGUF to *models_dir* (if not already there).
    2. Compute a manifest (sha256, size, timestamp).
    3. Add/update a ``[model_name]`` section in the config.ini with
       ``model = ...`` and sensible inference defaults.
    4. Attempt to validate the model loads via the server API.
    5. Return the manifest dict.

    Parameters
    ----------
    gguf_path:
        Path to the GGUF file to deploy.
    model_name:
        Name for the model — becomes the INI section name and the
        model ID exposed by the API.
    alias:
        Optional human-readable alias.
    models_dir:
        Directory where GGUF files are stored for serving.
    config_path:
        Path to the llama-server ``config.ini``.
    api_base:
        Base URL of the llama-server OpenAI-compatible API.

    Returns
    -------
    dict
        Manifest with keys: ``model_name``, ``alias``, ``gguf_path``,
        ``sha256``, ``file_size``, ``deployed_at``, ``validated``.
    """
    src = Path(gguf_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"GGUF file not found: {src}")

    dst_dir = Path(models_dir).expanduser().resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists() and dst.resolve() == src:
        logger.info("GGUF already in models directory: %s", dst)
    else:
        logger.info("Copying %s -> %s …", src, dst)
        shutil.copy2(str(src), str(dst))
        logger.info("Copy complete (%.1f MB)", dst.stat().st_size / 1_024_000)

    # Compute manifest
    manifest = _build_manifest(model_name, alias, str(dst))

    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path)
        logger.info("Loaded existing config: %s", config_path)
    else:
        logger.info("Creating new config: %s", config_path)

    section_params = {
        "model": str(dst),
        "ctx-size": str(_DEFAULT_CTX_SIZE),
        "temperature": str(_DEFAULT_TEMPERATURE),
        "flash-attn": _DEFAULT_FLASH_ATTN,
    }
    if alias:
        section_params["alias"] = alias

    # config[model_name] lowercases keys; use add_section/set to preserve case
    if model_name in config:
        logger.info("Updating existing model section [%s]", model_name)
    else:
        config.add_section(model_name)
    for key, val in section_params.items():
        config.set(model_name, key, val)

    _write_config(config, config_path)
    logger.info("Config updated — section [%s] written to %s", model_name, config_path)

    validated = False
    try:
        logger.info("Validating model via API …")
        result = validate_model(model_name, api_base=api_base, timeout=30)
        validated = result.get("ok", False)
        manifest["validated"] = validated
        if validated:
            logger.info("Model validated successfully")
        else:
            logger.warning("Model validation returned: %s", result.get("error", "unknown"))
    except Exception as exc:
        logger.warning(
            "Validation failed (server may need restart): %s", exc
        )
        manifest["validated"] = False
        manifest["validation_error"] = str(exc)

    return manifest


# ─── List ─────────────────────────────────────────────────────────────────────

def list_deployed(
    config_path: str = DEFAULT_CONFIG_PATH,
    api_base: str = DEFAULT_API_BASE,
) -> list[dict[str, Any]]:
    """
    List all deployed models and their current status.

    Reads the config.ini and optionally checks the server API for each
    model's runtime status.

    Returns
    -------
    list[dict]
        Each entry has keys: ``model_name``, ``source`` (``hf`` or
        ``model`` path), ``alias``, ``status`` (from API if available),
        and inference params.
    """
    config = configparser.ConfigParser()
    if not os.path.exists(config_path):
        logger.warning("Config not found: %s", config_path)
        return []

    config.read(config_path)

    api_models = _fetch_api_model_list(api_base)

    models: list[dict[str, Any]] = []
    for section in config.sections():
        entry: dict[str, Any] = {
            "model_name": section,
            "source": None,
            "alias": None,
            "status": None,
            "params": {},
        }
        for key, val in config.items(section):
            if key == "hf":
                entry["source"] = val
            elif key == "model":
                entry["source"] = val
            elif key == "alias":
                entry["alias"] = val
            elif key in ("hf-repo", "hf_repo"):
                entry["source"] = val
            else:
                entry["params"][key] = val

        for am in api_models:
            if am.get("id") == section:
                entry["status"] = am.get("status", {}).get("value")
                break

        if entry["status"] is None:
            entry["status"] = "unknown"

        models.append(entry)

    return models


# ─── Validate ─────────────────────────────────────────────────────────────────

def validate_model(
    model_name: str,
    api_base: str = DEFAULT_API_BASE,
    timeout: int = 60,
) -> dict[str, Any]:
    """
    Validate a deployed model responds correctly via the chat API.

    Sends a short test prompt and checks that the response is
    well-formed (status 200, non-empty content).

    Parameters
    ----------
    model_name:
        Model ID to test.
    api_base:
        Base URL of the llama-server API.
    timeout:
        Request timeout in seconds.

    Returns
    -------
    dict
        Keys: ``ok`` (bool), ``model``, ``response`` (snippet),
        ``latency_ms``, ``error`` (if any).
    """
    import requests as _requests

    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "Che, como va? Decime algo breve."}],
        "max_tokens": 50,
        "temperature": 0.5,
    }

    start = time.monotonic()
    try:
        resp = _requests.post(url, json=payload, timeout=timeout)
        elapsed = int((time.monotonic() - start) * 1000)
    except Exception as exc:
        return {
            "ok": False,
            "model": model_name,
            "error": f"API request failed: {exc}",
            "latency_ms": None,
        }

    if resp.status_code != 200:
        return {
            "ok": False,
            "model": model_name,
            "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
            "latency_ms": elapsed,
        }

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        return {
            "ok": False,
            "model": model_name,
            "error": "No choices in response",
            "latency_ms": elapsed,
        }

    content = choices[0].get("message", {}).get("content", "")
    if not content or not content.strip():
        return {
            "ok": False,
            "model": model_name,
            "error": "Empty response content",
            "latency_ms": elapsed,
        }

    return {
        "ok": True,
        "model": model_name,
        "response": content.strip()[:200],
        "latency_ms": elapsed,
    }


# ─── Undeploy ─────────────────────────────────────────────────────────────────

def undeploy_model(
    model_name: str,
    delete_gguf: bool = False,
    confirm: bool = True,
    config_path: str = DEFAULT_CONFIG_PATH,
) -> bool:
    """
    Remove a deployed model from the config and optionally delete its GGUF.

    Parameters
    ----------
    model_name:
        Model section name to remove from config.ini.
    delete_gguf:
        If True, also delete the GGUF file referenced by the ``model``
        key (skipped if the model uses ``hf`` / ``hf-repo``).
    confirm:
        If True, prompt for confirmation before deleting GGUF files.
        Skips confirmation when ``delete_gguf=False``.
    config_path:
        Path to the llama-server ``config.ini``.

    Returns
    -------
    bool
        True if the model was removed.
    """
    config = configparser.ConfigParser()
    if not os.path.exists(config_path):
        logger.warning("Config not found: %s", config_path)
        return False

    config.read(config_path)

    if model_name not in config:
        logger.warning("Model section [%s] not found in %s", model_name, config_path)
        return False

    gguf_path = None
    if delete_gguf:
        try:
            gguf_path = config.get(model_name, "model", fallback=None)
        except configparser.NoOptionError:
            pass

    config.remove_section(model_name)
    _write_config(config, config_path)
    logger.info("Removed section [%s] from %s", model_name, config_path)

    if delete_gguf and gguf_path:
        gguf = Path(gguf_path)
        if gguf.exists():
            if confirm:
                ans = input(
                    f"Delete GGUF file {gguf} ({gguf.stat().st_size / 1_024_000:.0f} MB)? [y/N] "
                )
                if ans.strip().lower() != "y":
                    logger.info("Skipping GGUF deletion")
                    return True
            gguf.unlink()
            logger.info("Deleted GGUF file: %s", gguf)
        else:
            logger.warning("GGUF file not found (already deleted?): %s", gguf)

    return True


# ─── Internal Helpers ─────────────────────────────────────────────────────────

def _build_manifest(
    model_name: str,
    alias: str,
    gguf_path: str,
) -> dict[str, Any]:
    """Compute a deployment manifest for a GGUF file."""
    path = Path(gguf_path)
    size_bytes = path.stat().st_size

    manifest: dict[str, Any] = {
        "model_name": model_name,
        "alias": alias or model_name,
        "gguf_path": str(path),
        "file_name": path.name,
        "file_size": size_bytes,
        "file_size_mb": round(size_bytes / 1_024_000, 1),
        "sha256": None,
        "deployed_at": datetime.now(timezone.utc).isoformat(),
        "validated": False,
    }

    logger.info("Computing SHA-256 of %s …", path.name)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    manifest["sha256"] = h.hexdigest()
    logger.info("SHA-256: %s", manifest["sha256"])

    return manifest


def _write_config(config: configparser.ConfigParser, path: str) -> None:
    """Write config.ini atomically via rename."""
    cfg_path = Path(path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cfg_path.with_suffix(".ini.tmp")
    with open(tmp, "w") as f:
        config.write(f)
    tmp.replace(cfg_path)
    logger.debug("Config written to %s", cfg_path)


def _fetch_api_model_list(api_base: str) -> list[dict[str, Any]]:
    """Fetch the list of models known to the server API."""
    import requests as _requests

    url = f"{api_base.rstrip('/')}/models"
    try:
        resp = _requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception:
        logger.debug("Could not fetch model list from API", exc_info=True)
    return []


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy, list, validate, or undeploy GGUF models from llama.cpp server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m trainer.deploy --gguf output/talker/q4_k_m.gguf --name my-model\n"
            "  python -m trainer.deploy --list\n"
            "  python -m trainer.deploy --validate --name my-model\n"
            "  python -m trainer.deploy --undeploy --name my-model\n"
        ),
    )

    # Mutually exclusive action group
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list",
        action="store_true",
        help="List all deployed models and their status",
    )
    group.add_argument(
        "--validate",
        action="store_true",
        help="Validate a deployed model via the API",
    )
    group.add_argument(
        "--undeploy",
        action="store_true",
        help="Undeploy (remove) a model from the config",
    )

    # Deploy options
    parser.add_argument(
        "--gguf",
        type=str,
        default=None,
        help="Path to the GGUF file to deploy",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Model name (INI section name, also the API model ID)",
    )
    parser.add_argument(
        "--alias",
        type=str,
        default=None,
        help="Optional human-readable alias for the model",
    )

    # Path overrides
    parser.add_argument(
        "--models-dir",
        type=str,
        default=DEFAULT_MODELS_DIR,
        help=f"Directory to store GGUF files (default: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to llama-server config.ini (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--api-base",
        type=str,
        default=DEFAULT_API_BASE,
        help=f"llama-server API base URL (default: {DEFAULT_API_BASE})",
    )

    # Undeploy options
    parser.add_argument(
        "--delete-gguf",
        action="store_true",
        default=False,
        help="When used with --undeploy, also delete the GGUF file",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        help="Skip confirmation prompts",
    )

    # Output
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output result as JSON (for scripting)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure basic logging — quiet on --json, informative otherwise
    level = logging.WARNING if args.json else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # ── List ─────────────────────────────────────────────────────────
    if args.list:
        models = list_deployed(
            config_path=args.config,
            api_base=args.api_base,
        )
        if args.json:
            print(json.dumps(models, indent=2, default=str))
        else:
            if not models:
                print("No deployed models found.", file=sys.stderr)
                return 0
            print(f"{'Model Name':<36} {'Source':<50} {'Status':<12}")
            print("-" * 100)
            for m in models:
                src = m["source"] or "—"
                if len(src) > 47:
                    src = src[:44] + "..."
                print(f"{m['model_name']:<36} {src:<50} {m.get('status','?'):<12}")
        return 0

    # ── Validate ─────────────────────────────────────────────────────
    if args.validate:
        if not args.name:
            parser.error("--name is required with --validate")
        result = validate_model(
            model_name=args.name,
            api_base=args.api_base,
        )
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            if result["ok"]:
                print(
                    f"✅ Model '{result['model']}' responds OK "
                    f"({result['latency_ms']} ms)"
                )
                print(f"   Response: \"{result['response']}\"")
            else:
                print(
                    f"❌ Model '{result.get('model', args.name)}' validation failed: "
                    f"{result.get('error', 'unknown error')}"
                )
                return 1
        return 0

    # ── Undeploy ─────────────────────────────────────────────────────
    if args.undeploy:
        if not args.name:
            parser.error("--name is required with --undeploy")
        ok = undeploy_model(
            model_name=args.name,
            delete_gguf=args.delete_gguf,
            confirm=not args.yes,
            config_path=args.config,
        )
        if args.json:
            print(json.dumps({"ok": ok}))
        else:
            if ok:
                print(f"Undeployed model '{args.name}'")
            else:
                print(f"Failed to undeploy model '{args.name}'", file=sys.stderr)
                return 1
        return 0

    # ── Deploy (default) ─────────────────────────────────────────────
    if not args.gguf or not args.name:
        parser.error("--gguf and --name are required for deployment (or use --list, --validate, --undeploy)")

    manifest = deploy_gguf(
        gguf_path=args.gguf,
        model_name=args.name,
        alias=args.alias or "",
        models_dir=args.models_dir,
        config_path=args.config,
        api_base=args.api_base,
    )

    if args.json:
        print(json.dumps(manifest, indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        print(f"  Model:     {manifest['model_name']}")
        print(f"  Alias:     {manifest['alias']}")
        print(f"  GGUF:      {manifest['gguf_path']}")
        print(f"  Size:      {manifest['file_size_mb']} MB")
        print(f"  SHA-256:   {manifest['sha256'][:16]}…")
        print(f"  Validated: {'✅' if manifest.get('validated') else '❌'}")
        if not manifest.get("validated") and manifest.get("validation_error"):
            print(f"  Note:      Server may need restart to pick up new model")
            print(f"             sudo systemctl restart llama-server.service")
        print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
