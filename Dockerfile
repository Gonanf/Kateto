# syntax=docker/dockerfile:1.7
#
# Build from Kateto with the sibling classifier as a named context:
# docker build --build-context classifier=../classifiers/mmbert -t kateto-local .

ARG LLAMA_REF=846e991ec3c7ccec49112ff2c5b00b710e5f551d
ARG WHISPER_REF=080bbbe85230f624f0b52127f1ae1218247989f9

FROM python:3.12-slim-bookworm AS native-build
ARG LLAMA_REF
ARG WHISPER_REF

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        ca-certificates \
        cmake \
        git \
        libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git llama.cpp \
    && cd llama.cpp \
    && git fetch --depth 1 origin "${LLAMA_REF}" \
    && git checkout "${LLAMA_REF}" \
    && cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=OFF \
        -DGGML_OPENMP=ON \
        -DLLAMA_BUILD_SERVER=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
    && cmake --build build --config Release --target llama-server -j"$(nproc)"

RUN git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git whisper.cpp \
    && cd whisper.cpp \
    && git fetch --depth 1 origin "${WHISPER_REF}" \
    && git checkout "${WHISPER_REF}" \
    && cmake -S . -B build \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=OFF \
        -DGGML_OPENMP=ON \
        -DWHISPER_BUILD_SERVER=ON \
        -DWHISPER_BUILD_TESTS=OFF \
        -DWHISPER_BUILD_EXAMPLES=ON \
    && cmake --build build --config Release --target whisper-server -j"$(nproc)"

FROM python:3.12-slim-bookworm AS runtime
ARG WHISPER_MODEL=ggml-large-v3-turbo.bin
ARG LLAMA_MODEL_REPO=Qwen/Qwen2.5-1.5B-Instruct-GGUF
ARG LLAMA_MODEL_FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/models/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    XDG_CONFIG_HOME=/opt/kateto-config \
    WHISPER_MODEL_FILE=${WHISPER_MODEL} \
    LLAMA_MODEL_REPO=${LLAMA_MODEL_REPO} \
    LLAMA_MODEL_FILE=${LLAMA_MODEL_FILE}

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ffmpeg \
        libgomp1 \
        libopenblas0 \
        libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=native-build /src/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=native-build /src/whisper.cpp/build/bin/whisper-server /usr/local/bin/whisper-server

WORKDIR /opt/kateto
COPY pyproject.toml uv.lock README.md ./
COPY kateto ./kateto
COPY config ./config
COPY docs ./docs
COPY public ./public

# BuildKit named contexts avoid vendoring the sibling classifier into Kateto.
COPY --from=classifier server.py pyproject.toml uv.lock /opt/classifier/

RUN python -m pip install --no-cache-dir uv \
    && uv sync --locked --no-dev \
    && uv pip install --system /opt/classifier \
    && python -m pip install --no-cache-dir huggingface_hub

COPY docker/config.toml /opt/kateto-config/kateto/config.toml
COPY docker/entrypoint.sh /usr/local/bin/kateto-entrypoint
RUN chmod 0755 /usr/local/bin/kateto-entrypoint \
    && mkdir -p /opt/kateto-config/kateto/voices \
    && cp -a config/defaults/voices/. /opt/kateto-config/kateto/voices/

RUN python - <<'PY'
import os
from huggingface_hub import hf_hub_download

hf_hub_download(
    repo_id="ggerganov/whisper.cpp",
    filename=os.environ["WHISPER_MODEL_FILE"],
    local_dir="/opt/models/whisper",
)
hf_hub_download(
    repo_id="Qdrant/all-MiniLM-L6-v2-onnx",
    filename="model.onnx",
    local_dir="/opt/models/classifier",
)
hf_hub_download(
    repo_id="Qdrant/all-MiniLM-L6-v2-onnx",
    filename="tokenizer.json",
)
hf_hub_download(
    repo_id=os.environ["LLAMA_MODEL_REPO"],
    filename=os.environ["LLAMA_MODEL_FILE"],
    local_dir="/opt/models/llama",
)
PY

EXPOSE 8090 8091 8092
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD python -c "import urllib.request; [urllib.request.urlopen(url, timeout=5) for url in ('http://127.0.0.1:8090/', 'http://127.0.0.1:8091/health', 'http://127.0.0.1:8092/health')]"

ENTRYPOINT ["/usr/local/bin/kateto-entrypoint"]
