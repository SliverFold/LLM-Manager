#!/usr/bin/env bash
# vllm-model-manager: install the Paiton big-brain (Qwen3.8) as a Docker container.
#
# This is the "known good" big-brain setup: a pre-built Paiton vLLM image
# (pinned vLLM + Paiton) + the Qwen3.8 model weights (pinned revisions) +
# the exact serve flags. It is AMD ROCm only (the image is ROCm 10).
#
# Steps:
#   1. Pull the pinned Docker image
#   2. Download the model weights (pinned HF revisions) into the host model-cache
#   3. Create + run the container with the big-brain mounts, GPU devices, env
#      and serve flags
#
# Idempotent: re-running updates the image (docker pull) and re-creates the
# container (docker rm + run) with the same flags. Model weights are reused
# (hf download is a no-op when the revision is already present).
#
# Usage: install_paiton.sh [port]   (default port 8000)
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

PORT="${1:-8000}"
CONTAINER_NAME="paiton-qwen38"
IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:qwen38-rocm10-vllm029-20261107-r2"
IMAGE_SHA="sha256:efe8c3f3242330009822e97afa10c10fb4a83ec250eb5e5468abc6a6650278c8"

# Host layout (mirrors the big brain): model-cache + runtime-cache under a
# stable base dir. Overridable so a fresh user can point at existing weights.
PAITON_BASE="${PAITON_BASE:-$HOME/Desktop/AI/paiton-vllm-plugin}"
TARGET_DIR="$PAITON_BASE/model-cache/qwen38-nvfp4"
DRAFT_DIR="$PAITON_BASE/model-cache/qwen38-dflash2"
W3ROT_DIR="$PAITON_BASE/model-cache/qwen38-w3rot-int3"
CACHE_DIR="$PAITON_BASE/runtime-cache/qwen38-rocm10-20261107"

# Pinned HF revisions (must match the image's expected checkpoint)
TARGET_REPO="unsloth/Qwen3.8-27B-NVFP4"
TARGET_REV="f0b7c9e722f5565102fff8481c99e4d86ae099c7"
DRAFT_REPO="tcclaviger/Qwen3.8-27B-DFlash2-FP8"
DRAFT_REV="ee0cb26a8279b7910cc28d82a8a3e15e4728d56f"
W3ROT_REPO="EliovpAI/Qwen3.8-27B-W3Rot-INT3-Paiton-RDNA4"
W3ROT_REV="aee42dfdb78e851462743120a575bf2d6f7b9882"

# --- 0. Preconditions ---
command -v docker >/dev/null 2>&1 || { log "ERROR: docker not found — install Docker first"; exit 1; }
# AMD GPU check (the image is ROCm-only)
if ! command -v rocm-smi >/dev/null 2>&1 && [ ! -d /opt/rocm ]; then
  log "ERROR: no AMD GPU stack found (rocm-smi / /opt/rocm) — the Paiton image is ROCm-only"
  exit 1
fi
log "GPU: $(rocm-smi --showproductname --json 2>/dev/null | grep -oE '"GFX Version": *"[^"]+"' | head -1 || echo 'AMD GPU')"

# --- 1. Pull the pinned image ---
log "Pulling Paiton image ($IMAGE)…"
docker pull "$IMAGE@$IMAGE_SHA" || docker pull "$IMAGE"
log "Image ready"

# --- 2. Download the model weights (pinned revisions) ---
mkdir -p "$TARGET_DIR" "$DRAFT_DIR" "$W3ROT_DIR" "$CACHE_DIR"

# Resolve a working `hf` (Hugging Face CLI). Prefer the global `hf`; otherwise
# create a throwaway venv (system Python on Arch/CachyOS is PEP 668 externally
# managed, so a plain `pip install` fails).
if command -v hf >/dev/null 2>&1; then
  HF="hf"
elif python3 -c 'import huggingface_hub' >/dev/null 2>&1; then
  HF="python3 -m huggingface_hub"
else
  log "No 'hf' on PATH — creating a venv for the weight download…"
  HF_VENV="$HOME/.cache/paiton-hf-venv"
  python3 -m venv "$HF_VENV" || { log "ERROR: could not create a venv (install python3-venv)"; exit 1; }
  "$HF_VENV/bin/pip" install -q huggingface_hub || { log "ERROR: could not install huggingface_hub in the venv"; exit 1; }
  HF="$HF_VENV/bin/python -m huggingface_hub"
fi

download() { # $1=repo $2=revision $3=local-dir
  log "Downloading $1 (revision ${2:0:12}…) → $3"
  $HF download "$1" --revision "$2" --local-dir "$3"
}

[ -f "$TARGET_DIR/config.json" ] || download "$TARGET_REPO" "$TARGET_REV" "$TARGET_DIR"
[ -f "$DRAFT_DIR/config.json" ]  || download "$DRAFT_REPO"  "$DRAFT_REV"  "$DRAFT_DIR"
[ -f "$W3ROT_DIR/config.json" ]  || download "$W3ROT_REPO"  "$W3ROT_REV"  "$W3ROT_DIR"
log "Model weights ready"

# --- 3. Recreate the container with the big-brain config ---
# GPU index for the R9700 (index 0 by default; override with PAITON_GPU)
GPU_INDEX="${PAITON_GPU:-0}"
ROCR_DEV="$(rocm-smi --showuniqueid --json 2>/dev/null | grep -oE '"Unique ID": *"[^"]+"' | head -1 | grep -oE '[a-f0-9]{16}' || true)"

log "Recreating container '$CONTAINER_NAME' (port $PORT, GPU $GPU_INDEX)…"
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  --device /dev/kfd \
  --device /dev/dri \
  -e "HIP_VISIBLE_DEVICES=$GPU_INDEX" \
  -e "CUDA_VISIBLE_DEVICES=$GPU_INDEX" \
  ${ROCR_DEV:+-e "ROCR_VISIBLE_DEVICES=GPU-$ROCR_DEV"} \
  -e "HIP_PLATFORM=amd" \
  -e "HIP_ARCHITECTURES=gfx1201" \
  -e "HIP_FORCE_DEV_KERNARG=1" \
  -e "PYTORCH_NVML_BASED_CUDA_CHECK=1" \
  -v "$TARGET_DIR:/models/target:ro" \
  -v "$DRAFT_DIR:/models/draft:ro" \
  -v "$W3ROT_DIR:/models/w3rot:ro" \
  -v "$CACHE_DIR:/cache:rw" \
  -p "$PORT:8000" \
  "$IMAGE" \
  serve /models/target \
    --tokenizer /models/target \
    --served-model-name Qwen3.8 \
    --host 127.0.0.1 \
    --port 8000 \
    --tensor-parallel-size 1 \
    --dtype bfloat16 \
    --max-model-len 245000 \
    --max-num-seqs 8 \
    --max-num-batched-tokens 4096 \
    --kv-cache-dtype fp8 \
    --kv-cache-memory-bytes 9256000000 \
    --gpu-memory-utilization 0.98 \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --safetensors-load-strategy lazy \
    --attention-backend R4D \
    --compilation-config '{"cudagraph_capture_sizes": [1, 2, 4, 8, 16, 24, 32, 40, 48, 56, 64], "pass_config": {"fuse_norm_quant": true, "fuse_act_quant": true}}' \
    --speculative-config '{"method": "dflash", "model": "/models/draft", "num_speculative_tokens": 7, "draft_tensor_parallel_size": 1, "attention_backend": "TRITON_ATTN", "max_model_len": 245000, "disable_padded_drafter_batch": true, "draft_sample_method": "greedy"}' \
    --mamba-cache-mode align \
    --mamba-cache-dtype bfloat16 \
    --mamba-ssm-cache-dtype float16 \
    --no-async-scheduling \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --override-generation-config '{"temperature": 0.7, "top_p": 0.95, "top_k": 20}' \
    --seed 42 \
    --mm-processor-kwargs '{"max_pixels": 8294400}' \
    --mm-processor-cache-gb 1 \
    --default-chat-template-kwargs '{"enable_thinking": true}' \
    --enable-prompt-tokens-details
log "Container started (first load ~3-4 min; wait for /health)"

# --- 4. Wait for health ---
log "Waiting for the server to become healthy…"
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    log "Paiton big-brain healthy on :$PORT"
    log "API: http://127.0.0.1:$PORT/v1  model: Qwen3.8"
    exit 0
  fi
  sleep 5
done
log "WARNING: server not healthy yet — check 'docker logs $CONTAINER_NAME'"
log "API: http://127.0.0.1:$PORT/v1  model: Qwen3.8"
