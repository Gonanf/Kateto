#!/bin/bash
# Setup llama.cpp baseline models for Kateto Manager agents
# Creates symlinks from HuggingFace Hub cache to apps/trainer/llama-models/
# 
# Usage: bash apps/trainer/scripts/setup_llamacpp.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRAINER_DIR="$(dirname "$SCRIPT_DIR")"
MODELS_DIR="$TRAINER_DIR/llama-models"

echo "=== Kateto llama.cpp Model Setup ==="
echo "Models directory: $MODELS_DIR"
mkdir -p "$MODELS_DIR"

# HuggingFace Hub cache paths
HF_CACHE="$HOME/.cache/huggingface/hub"

# --- Bonsai 8B GGUF (KatetoTalker / KatetoDreamer) ---
BONSAI_SNAPSHOT="$HF_CACHE/models--prism-ml--Bonsai-8B-gguf/snapshots/48516770dd04643643e9f9019a2a349cf26c5dbd"
BONSAI_GGUF="$BONSAI_SNAPSHOT/Bonsai-8B-Q1_0.gguf"
BONSAI_TARGET="$MODELS_DIR/Bonsai-8B-Q1_0.gguf"

if [ -f "$BONSAI_GGUF" ]; then
  echo "[OK] Bonsai 8B GGUF found in HF cache at $BONSAI_GGUF"
  if [ ! -L "$BONSAI_TARGET" ] || [ ! -e "$BONSAI_TARGET" ]; then
    ln -sf "$BONSAI_GGUF" "$BONSAI_TARGET"
    echo "  -> Symlinked to $BONSAI_TARGET"
  else
    echo "  -> Symlink already exists at $BONSAI_TARGET"
  fi
else
  echo "[DOWNLOAD] Bonsai 8B GGUF not in HF cache, downloading..."
  huggingface-cli download prism-ml/Bonsai-8B-gguf --local-dir-use-symlinks False
  # Re-check after download
  if [ -f "$BONSAI_GGUF" ]; then
    ln -sf "$BONSAI_GGUF" "$BONSAI_TARGET"
    echo "  -> Symlinked to $BONSAI_TARGET"
  else
    echo "  [WARN] Download completed but file not found. Trying wget fallback..."
    wget -O "$BONSAI_TARGET" "https://huggingface.co/prism-ml/Bonsai-8B-gguf/resolve/main/Bonsai-8B-Q1_0.gguf"
  fi
fi

# --- Qwen3.5-0.8B GGUF (KatetoProductOwner) ---
QWEN_SNAPSHOT="$HF_CACHE/models--unsloth--Qwen3.5-0.8B-GGUF/snapshots/6ab461498e2023f6e3c1baea90a8f0fe38ab64d0"
QWEN_GGUF="$QWEN_SNAPSHOT/Qwen3.5-0.8B-Q4_K_M.gguf"
QWEN_TARGET="$MODELS_DIR/Qwen3.5-0.8B-Q4_K_M.gguf"

if [ -f "$QWEN_GGUF" ]; then
  echo "[OK] Qwen3.5-0.8B GGUF found in HF cache at $QWEN_GGUF"
  if [ ! -L "$QWEN_TARGET" ] || [ ! -e "$QWEN_TARGET" ]; then
    ln -sf "$QWEN_GGUF" "$QWEN_TARGET"
    echo "  -> Symlinked to $QWEN_TARGET"
  else
    echo "  -> Symlink already exists at $QWEN_TARGET"
  fi
else
  echo "[DOWNLOAD] Qwen3.5-0.8B GGUF not in HF cache, downloading..."
  huggingface-cli download unsloth/Qwen3.5-0.8B-GGUF --local-dir-use-symlinks False
  if [ -f "$QWEN_GGUF" ]; then
    ln -sf "$QWEN_GGUF" "$QWEN_TARGET"
    echo "  -> Symlinked to $QWEN_TARGET"
  else
    echo "  [WARN] Download completed but file not found. Trying wget fallback..."
    wget -O "$QWEN_TARGET" "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf"
  fi
fi

echo ""
echo "=== Summary ==="
ls -lh "$MODELS_DIR"
echo ""
echo "Done! Models ready for llama.cpp server."
echo "Start server with: bash $TRAINER_DIR/llama-models/start_server.sh"
