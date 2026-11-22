#!/usr/bin/env bash
# vllm-model-manager: start the DUAL-CARD setup (Qwen3.8-27B NVFP4, port 8002).
# R9700 (32GB) + 9070 (16GB), both gfx1201.
#
# IMAGE: beledarian/vllm-rocm10.1-rccl-nohostcall:2.27.7 — derived from official
# rocm/vllm ROCm 10.1 (vLLM 0.29.1, py3.14, native gfx1201 kernels) with a
# no-hostcall RCCL 2.27.7 (rebuilt with NDEBUG so the device kernels carry no
# hidden_hostcall_buffer — required because the R9700's chipset-routed link has
# no PCIe atomics, which stock RCCL >= 7.2.1 hard-depends on). See
# Memory/system/dual-card.md (LATEST) for the full build/verify/probe record.
# The paiton image (ROCm 10.0 userland) has NO gfx1201 kernels: the 9070 fails
# with 'hip: invalid argument' and RCCL collectives fail with 'the operation
# cannot be performed in the present state'.
#
# MODEL: unsloth/Qwen3.8-27B-NVFP4 — compressed-tensors mixed-precision
# (FP8 + NVFP4, MTP head in BF16). Identical to the local checkpoint at
# paiton-vllm-plugin/model-cache/qwen38-nvfp4 (same sizes + config), which
# the big brain runs. Loaded from the HF cache (pre-downloaded).
#
# PARALLEL MODE (switchable via PARALLEL_MODE env var, default "tp"):
#   tp = tensor-parallel (all-reduce after every layer; R9700's x4 link is
#        the bottleneck — slow prefill, fast generation)
#   pp = pipeline-parallel (one handoff at the stage boundary — faster prefill)
#   Usage: PARALLEL_MODE=pp ./mgr_dual_start.sh
#
# CUTOVER: stop big brain (8000) + small brain (8001) first, and move the
# display to the R9700 (the 9070 needs its full ~16GB for the dual model).
set -euo pipefail
PARALLEL_MODE="${PARALLEL_MODE:-tp}"
# PP layer partition (PP only): comma list of per-rank layer counts, must sum to 64.
# rank0 = R9700 (32GB), rank1 = 9070 (16GB). The growing KV cache lives ONLY in the
# 16 full-attention layers (every 4th: idx 3,7,...,63); the 48 linear-attention layers
# carry a fixed (sequence-independent) state. So we put the full-attn layers on the
# R9700 (the KV GPU) and as many layers as possible on the 9070. Default 48,16 gives the
# 9070 16 layers (4 full-attn) -> ~572K context (max). Override: PP_PARTITION=56,8 ./mgr_dual_start.sh
# (48,16 = max context ~572K; 56,8 = 9070 least loaded ~381K; 34,30 = most balanced ~164K)
PP_PARTITION="${PP_PARTITION:-48,16}"
LOG="/home/j/logs/vllm_dual_start.log"
mkdir -p /home/j/logs
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if [ "$PARALLEL_MODE" = "pp" ]; then
  PARALLEL_FLAG="--pipeline-parallel-size 2"
  MODE_LABEL="pipeline-parallel"
  # PP requires --language-model-only (the vision-language wrapper Qwen3_5ForConditionalGeneration
  # does NOT implement SupportsPP; the text-only Qwen3_5ForCausalLM does). It also drops MTP
  # (the MTP draft class lacks SupportsPP, and PP + spec-decode is an upstream vLLM incompat).
  EXTRA_FLAGS="--language-model-only"
  PP_ENV="-e VLLM_PP_LAYER_PARTITION=$PP_PARTITION"
  # PP is the long-context mode: raise the context ceiling (KV is split across both ranks).
  MAX_MODEL_LEN="${PP_MAX_MODEL_LEN:-155000}"
  # No MTP in PP (the MTP draft class lacks SupportsPP).
  SPEC_CONFIG=""
else
  PARALLEL_FLAG="--tensor-parallel-size 2"
  MODE_LABEL="tensor-parallel"
  EXTRA_FLAGS=""
  PP_ENV=""
  MAX_MODEL_LEN=32768
  SPEC_CONFIG="--speculative-config '{\"method\":\"mtp\",\"num_speculative_tokens\":2}'"
fi

log "=== mgr_dual_start.sh invoked ==="
log "PARALLEL_MODE=$PARALLEL_MODE"
log "PATH=$PATH"
log "HOME=$HOME"
log "USER=$USER"
log "SHELL=$SHELL"
log "docker: $(docker --version 2>&1 || echo 'docker not found')"
log "container (running): $(docker ps -q -f name=vllm-qwen38 2>&1 || echo 'none')"
log "container (all): $(docker ps -aq -f name=vllm-qwen38 2>&1 || echo 'none')"

if docker ps -q -f name=vllm-qwen38 | grep -q .; then
  log "vllm-qwen38 already running"
  exit 0
fi
docker rm -f vllm-qwen38 2>/dev/null || true
log "Running docker run for vllm-qwen38 (27B NVFP4, $MODE_LABEL)"
# ENV:
#   VLLM_ROCM_USE_AITER=1 : AMD's optimized attention/GEMM kernels (hybrid
#                           linear/full attention + NVFP4 on RDNA4)
#   NCCL_P2P_DISABLE=1    : no PCIe atomics on the chipset-routed R9700 link;
#                           RCCL falls back to SHM transport (works)
#   NCCL_DEBUG=INFO       : diagnostics in vllm_dual.log
#   HF_HOME=/root/.cache/huggingface : model resolved from the host HF cache
docker run -d --name vllm-qwen38 \
  --device /dev/kfd --device /dev/dri \
  --network=host --ipc=host \
  --group-add=video --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -e VLLM_ROCM_USE_AITER=1 \
  -e HIP_VISIBLE_DEVICES=0,1 \
  -e NCCL_P2P_DISABLE=1 \
  -e HSA_ENABLE_SDMA=0 \
  -e NCCL_DEBUG=INFO \
  -e VLLM_NO_USAGE_STATS=1 \
  -e HF_HOME="/root/.cache/huggingface" \
  $PP_ENV \
  -v /home/j/.cache/huggingface:/root/.cache/huggingface:ro \
  beledarian/vllm-rocm10.1-rccl-nohostcall:2.27.7 \
  vllm serve unsloth/Qwen3.8-27B-NVFP4 \
    --served-model-name Qwen3.8 \
    --host 0.0.0.0 --port 8002 \
    $PARALLEL_FLAG \
    $EXTRA_FLAGS \
    --max-model-len $MAX_MODEL_LEN \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.94 \
    --enforce-eager \
    --kv-cache-dtype fp8 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    $SPEC_CONFIG \
    2>&1 | tee -a "$LOG"
log "docker run exit: ${PIPESTATUS[0]}"
pkill -f "docker logs -f vllm-qwen38" 2>/dev/null || true
nohup docker logs -f vllm-qwen38 >> /home/j/logs/vllm_dual.log 2>&1 &
log "vllm-qwen38 (27B NVFP4, $MODE_LABEL) starting on R9700+9070 port 8002 (log: /home/j/logs/vllm_dual.log)"
log "=== mgr_dual_start.sh finished ==="
