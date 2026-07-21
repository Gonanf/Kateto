#!/usr/bin/env bash
set -Eeuo pipefail

cleanup() {
    local status=$?
    for pid in "${KATETO_PID:-}" "${LLAMA_PID:-}" "${CLASSIFIER_PID:-}" "${WHISPER_PID:-}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill "${pid}" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
    exit "${status}"
}
trap cleanup EXIT INT TERM

whisper-server \
    --model "/opt/models/whisper/${WHISPER_MODEL_FILE}" \
    --host 0.0.0.0 \
    --port 8090 \
    --threads "${WHISPER_THREADS:-4}" \
    --no-gpu \
    > >(sed -u 's/^/[whisper] /') 2>&1 &
WHISPER_PID=$!

python /opt/classifier/server.py \
    --host 0.0.0.0 \
    --port 8091 \
    --model /opt/models/classifier/model.onnx \
    --no-vulkan \
    > >(sed -u 's/^/[classifier] /') 2>&1 &
CLASSIFIER_PID=$!

llama-server \
    --model "/opt/models/llama/${LLAMA_MODEL_FILE}" \
    --host 0.0.0.0 \
    --port 8092 \
    --ctx-size "${LLAMA_CTX_SIZE:-4096}" \
    --n-predict "${LLAMA_N_PREDICT:-768}" \
    --parallel 1 \
    > >(sed -u 's/^/[llama] /') 2>&1 &
LLAMA_PID=$!

uv run kateto run > >(sed -u 's/^/[kateto] /') 2>&1 &
KATETO_PID=$!

wait "${KATETO_PID}"
