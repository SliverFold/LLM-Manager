#!/usr/bin/env bash
# vllm-model-manager: start the DUAL-CARD TP2 setup (Qwen3.8-27B NVFP4, port 8002).
# R9700 (32GB) + 9070 (16GB), both gfx1201. Tensor-parallel (MTP, 32K context).
# Stops the PP2 container first (if running) — both use the same two GPUs + port.
#
# IMAGE: beledarian/vllm-rocm10.1-rccl-nohostcall:2.27.7 (no-hostcall RCCL 2.27.7 —
# required because the R9700's chipset-routed link has no PCIe atomics). See
# Memory/system/dual-card.md (LATEST) for the full build/verify/probe record.
set -euo pipefail
NAME="vllm-qwen38-tp"
LOG="/home/j/logs/vllm_dual_tp_start.log"
mkdir -p /home/j/logs
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# Stop the PP2 container first (if running) — both use the same GPUs + port 8002.
docker stop vllm-qwen38-pp 2>/dev/null || true
docker rm -f vllm-qwen38-pp 2>/dev/null || true

if docker ps -q -f name="$NAME" | grep -q .; then
  log "$NAME already running"
  exit 0
fi
docker rm -f "$NAME" 2>/dev/null || true

log "Running docker run for $NAME (27B NVFP4, tensor-parallel)"
docker run -d --name "$NAME" \
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
  -v /home/j/.cache/huggingface:/root/.cache/huggingface:ro \
  beledarian/vllm-rocm10.1-rccl-nohostcall:2.27.7 \
  vllm serve unsloth/Qwen3.8-27B-NVFP4 \
    --served-model-name Qwen3.8 \
    --host 0.0.0.0 --port 8002 \
    --tensor-parallel-size 2 \
    --max-model-len 32768 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.94 \
    --enforce-eager \
    --kv-cache-dtype fp8 \
    --reasoning-parser qwen3 \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --speculative-config '{"method":"mtp","num_speculative_tokens":2}' \
    2>&1 | tee -a "$LOG"
log "docker run exit: ${PIPESTATUS[0]}"
pkill -f "docker logs -f $NAME" 2>/dev/null || true
nohup docker logs -f "$NAME" >> /home/j/logs/vllm_dual_tp.log 2>&1 &
log "$NAME (27B NVFP4, tensor-parallel) starting on R9700+9070 port 8002 (log: /home/j/logs/vllm_dual_tp.log)"
log "=== mgr_dual_tp_start.sh finished ==="
