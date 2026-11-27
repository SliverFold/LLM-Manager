#!/usr/bin/env bash
# vllm-model-manager: install a Paiton release model as a Docker container.
#
# Each Paiton chat/LLM model in the paiton-vllm-plugin repo has a Docker
# launcher. Two families:
#   - Qwen3.8 27B: the "known good" big-brain setup — a pre-built Paiton vLLM
#     image + pinned Qwen3.8 model weights + the exact serve flags.
#   - The others (GPT-OSS 20B, MiniCPM5 2B, Ornith 1.5, Qwen3-Coder 30B,
#     Qwen3.8 NEO CODER MAX): a pinned Paiton image that pulls/downloads its
#     own weights on first run (no separate weight download).
#
# Idempotent: re-running updates the image (docker pull) and re-creates the
# container. Qwen3.8 weights are reused (hf download is a no-op when the
# revision is already present).
#
# Usage: install_paiton.sh <model-slug> [port]
#   model-slug: qwen38 | qwen38-mxfp4 | gpt-oss-20b | minicpm5-2b | ornith-1.5 |
#               qwen3-coder-30b | qwen38-neo-coder
#   port:       host port for the API (default per model)
set -euo pipefail
log() { echo "[$(date '+%Y-%d %H:%M:%S')] $*"; }

MODEL="${1:-qwen38}"
PORT="${2:-}"

# --- Per-model config ---
case "$MODEL" in
  qwen38)
    CONTAINER_NAME="paiton-qwen38"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:qwen38-rocm10-vllm029-20261107-r2"
    IMAGE_SHA="sha256:efe8c3f3242330009822e97afa10c10fb4a83ec250eb5e5468abc6a6650278c8"
    PORT="${PORT:-8000}"
    KIND="qwen38"
    ;;
  qwen38-mxfp4)
    CONTAINER_NAME="paiton-qwen38-mxfp4"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:qwen38-rocm10-vllm029-20261107-r2"
    IMAGE_SHA="sha256:efe8c3f3242330009822e97afa10c10fb4a83ec250eb5e5468abc6a6650278c8"
    PORT="${PORT:-8001}"
    KIND="qwen38-mxfp4"
    ;;
  gpt-oss-20b)
    CONTAINER_NAME="paiton-gpt-oss"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:gpt-oss-20b-mxfp4-rdna4-v1.0.0"
    PORT="${PORT:-8020}"
    KIND="serve"
    ;;
  minicpm5-2b)
    CONTAINER_NAME="paiton-minicpm5-2b"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:minicpm5-2b-w4a16-rdna4-v1.0.0"
    PORT="${PORT:-8036}"
    KIND="serve"
    ;;
  ornith-1.5)
    CONTAINER_NAME="paiton-ornith"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:ornith15-mxfp4-rdna4-v1.0.0"
    PORT="${PORT:-8000}"
    KIND="serve"
    ;;
  qwen3-coder-30b)
    CONTAINER_NAME="paiton-qwen3-coder"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin:qwen3-coder-30b-awq-rdna4-v1.0.0"
    PORT="${PORT:-8010}"
    KIND="serve"
    ;;
  qwen38-neo-coder)
    CONTAINER_NAME="paiton-qwen38-neo"
    IMAGE="ghcr.io/eliovp/paiton-vllm-plugin@sha256:534287969135f581744ae481b578599468b0bf7ac9a4051b0941500e4c18da4d"
    PORT="${PORT:-8000}"
    KIND="serve"
    ;;
  *)
    log "ERROR: unknown model slug '$MODEL' (expected qwen38, qwen38-mxfp4, gpt-oss-20b, minicpm5-2b, ornith-1.5, qwen3-coder-30b, or qwen38-neo-coder)"
    exit 1
    ;;
esac

# --- 0. Preconditions ---
command -v docker >/dev/null 2>&1 || { log "ERROR: docker not found — install Docker first"; exit 1; }
# AMD GPU check (the images are ROCm-only)
if ! command -v rocm-smi >/dev/null 2>&1 && [ ! -d /opt/rocm ]; then
  log "ERROR: no AMD GPU stack found (rocm-smi / /opt/rocm) — the Paiton images are ROCm-only"
  exit 1
fi
log "GPU: $(rocm-smi --showproductname --json 2>/dev/null | grep -oE '"GFX Version": *"[^"]+"' | head -1 || echo 'AMD GPU')"
log "Model: $MODEL  Container: $CONTAINER_NAME  Port: $PORT"

# --- 1. Pull the pinned image ---
log "Pulling Paiton image ($IMAGE)…"
if [ "$KIND" = "qwen38" ] || [ "$KIND" = "qwen38-mxfp4" ]; then
  docker pull "$IMAGE@$IMAGE_SHA" || docker pull "$IMAGE"
else
  docker pull "$IMAGE"
fi
log "Image ready"

# GPU index for the R9700 (index 0 by default; override with PAITON_GPU)
GPU_INDEX="${PAITON_GPU:-0}"
ROCR_DEV="$(rocm-smi --showuniqueid --json 2>/dev/null | grep -oE '"Unique ID": *"[^"]+"' | head -1 | grep -oE '[a-f0-9]{16}' || true)"

# --- 2. Recreate the container ---
log "Recreating container '$CONTAINER_NAME' (port $PORT, GPU $GPU_INDEX)…"
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

if [ "$KIND" = "qwen38" ] || [ "$KIND" = "qwen38-mxfp4" ]; then
  # Qwen3.8: download the pinned weights, then run with the release serve flags.
  # Two weight choices: 3-bit W3A4 (NVFP4 target + W3 int3 rotation + DFlash2
  # FP8 draft, the fastest) and MXFP4 (the most accurate, base download alone).
  PAITON_BASE="${PAITON_BASE:-$HOME/Desktop/AI/paiton-vllm-plugin}"
  DRAFT_DIR="$PAITON_BASE/model-cache/qwen38-dflash2"
  CACHE_DIR="$PAITON_BASE/runtime-cache/qwen38-rocm10-20261107"
  if [ "$KIND" = "qwen38" ]; then
    TARGET_DIR="$PAITON_BASE/model-cache/qwen38-nvfp4"
    W3ROT_DIR="$PAITON_BASE/model-cache/qwen38-w3rot-int3"
    TARGET_REPO="unsloth/Qwen3.8-27B-NVFP4"
    TARGET_REV="f0b7c9e722f5565102fff8481c99e4d86ae099c7"
  else
    TARGET_DIR="$PAITON_BASE/model-cache/qwen38-mxfp4"
    W3ROT_DIR=""
    TARGET_REPO="amd/Qwen3.8-27B-Quark-AWQ-MXFP4"
    TARGET_REV="5233554c5fa56afda40150556b95573c2d7d29c0"
  fi
  mkdir -p "$TARGET_DIR" "$DRAFT_DIR" "$CACHE_DIR"
  if [ -n "$W3ROT_DIR" ]; then
    mkdir -p "$W3ROT_DIR"
  fi

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
  [ -f "$DRAFT_DIR/config.json" ]  || download "tcclaviger/Qwen3.8-27B-DFlash2-FP8" "ee0cb26a8279b7910cc28d82a8a3e15e4728d56f" "$DRAFT_DIR"
  if [ -n "$W3ROT_DIR" ]; then
    [ -f "$W3ROT_DIR/config.json" ] || download "EliovpAI/Qwen3.8-27B-W3Rot-INT3-Paiton-RDNA4" "aee42dfdb78e851462743120a575bf2d6f7b9882" "$W3ROT_DIR"
  fi
  log "Model weights ready"

  if [ "$KIND" = "qwen38" ]; then
    # 3-bit W3A4: NVFP4 target + W3 int3 rotation + DFlash2 FP8 draft, long
    # context (245K), vision, prefix caching.
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
  else
    # MXFP4: the most accurate weights, from the base download alone — text-only
    # (no vision), 65K context, no prefix caching (the 65K release mode).
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
        --max-model-len 65536 \
        --max-num-seqs 8 \
        --max-num-batched-tokens 4096 \
        --kv-cache-dtype fp8 \
        --kv-cache-memory-bytes 6535819798 \
        --gpu-memory-utilization 0.98 \
        --no-enable-prefix-caching \
        --enable-chunked-prefill \
        --language-model-only \
        --safetensors-load-strategy lazy \
        --attention-backend R4D \
        --compilation-config '{"cudagraph_capture_sizes": [1, 2, 4, 8, 16, 24, 32, 40, 48, 56, 64], "pass_config": {"fuse_norm_quant": true, "fuse_act_quant": true}}' \
        --speculative-config '{"method": "dflash", "model": "/models/draft", "num_speculative_tokens": 7, "draft_tensor_parallel_size": 1, "attention_backend": "TRITON_ATTN", "max_model_len": 65536, "disable_padded_drafter_batch": true, "draft_sample_method": "greedy"}' \
        --mamba-cache-mode align \
        --mamba-cache-dtype bfloat16 \
        --mamba-ssm-cache-dtype float16 \
        --no-async-scheduling \
        --enable-auto-tool-choice \
        --tool-call-parser qwen3_coder \
        --reasoning-parser qwen3 \
        --override-generation-config '{"temperature": 0.7, "top_p": 0.95, "top_k": 20}' \
        --seed 42
  fi
else
  # The other models: a pinned Paiton image that pulls/downloads its own weights
  # on first run. Container port is 8000 (or 8020/8036 for GPT-OSS/MiniCPM5).
  CONTAINER_PORT=8000
  case "$MODEL" in
    gpt-oss-20b) CONTAINER_PORT=8020 ;;
    minicpm5-2b) CONTAINER_PORT=8036 ;;
  esac
  CACHE_DIR="${HOME}/.cache/paiton-$MODEL"
  mkdir -p "$CACHE_DIR"
  docker run -d \
    --name "$CONTAINER_NAME" \
    --device /dev/kfd \
    --device /dev/dri \
    --group-add video \
    --ipc host \
    -e "HIP_VISIBLE_DEVICES=$GPU_INDEX" \
    -e "CUDA_VISIBLE_DEVICES=$GPU_INDEX" \
    -e "GPU_MAX_HW_QUEUES=1" \
    -p "$PORT:$CONTAINER_PORT" \
    -v "$CACHE_DIR:/models/cache" \
    "$IMAGE"
fi
log "Container started (first load ~3-4 min; wait for /health)"

# --- 3. Wait for health ---
log "Waiting for the server to become healthy…"
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    log "Paiton $MODEL healthy on :$PORT"
    log "API: http://127.0.0.1:$PORT/v1"
    exit 0
  fi
  sleep 5
done
log "WARNING: server not healthy yet — check 'docker logs $CONTAINER_NAME'"
log "API: http://127.0.0.1:$PORT/v1"
