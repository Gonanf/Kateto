#!/bin/bash
# Start llama.cpp server with Kateto baseline models
# Serves OpenAI-compatible API on port 11434
# Uses --models-preset to load model configs from ~/.config/llama/config.ini
#
# Usage: bash apps/trainer/llama-models/start_server.sh

set -euo pipefail

CONFIG_FILE="$HOME/.config/llama/config.ini"
HOST="0.0.0.0"
PORT=11434

echo "=== Kateto llama.cpp Server ==="
echo "Config: $CONFIG_FILE"
echo "Listening: $HOST:$PORT"

# Validate config exists
if [ ! -f "$CONFIG_FILE" ]; then
  echo "ERROR: Config file not found at $CONFIG_FILE"
  echo "Create it or run: bash apps/trainer/scripts/setup_llamacpp.sh"
  exit 1
fi

# Kill existing server process if running
EXISTING_PID=$(pgrep -x "llama-server" 2>/dev/null || true)
if [ -n "$EXISTING_PID" ]; then
  echo "Stopping existing llama-server (PID: $EXISTING_PID)..."
  kill "$EXISTING_PID" 2>/dev/null || true
  sleep 2
  # Force kill if still running
  if kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Force stopping..."
    kill -9 "$EXISTING_PID" 2>/dev/null || true
    sleep 1
  fi
fi

# Start server with models preset
echo "Starting llama-server..."
nohup llama-server \
  --host "$HOST" \
  --port "$PORT" \
  --models-preset "$CONFIG_FILE" \
  --sleep-idle-seconds 600 \
  -lv 10 \
  > /tmp/llama-server.log 2>&1 &

PID=$!
echo "llama-server started with PID: $PID"
echo "Log: /tmp/llama-server.log"
echo "API: http://localhost:$PORT/v1"
echo ""
echo "Available models (from config.ini):"
grep -E '^\[' "$CONFIG_FILE" | tr -d '[]' | while read -r model; do
  echo "  - $model"
done

# Wait for server to be ready
echo ""
echo "Waiting for server to be ready..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$PORT/v1/models" > /dev/null 2>&1; then
    echo "Server ready after ${i}s!"
    break
  fi
  sleep 1
done

# Print loaded model status
echo ""
echo "=== Model Status ==="
curl -s "http://localhost:$PORT/v1/models" | python3 -m json.tool 2>/dev/null || echo "(could not parse model list)"
