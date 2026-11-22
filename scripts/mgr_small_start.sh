#!/usr/bin/env bash
# vllm-model-manager: start the small brain (Qwen3-14B NVFP4, 9070, port 8001).
# Coexists with the big brain (R9700, port 8000) — separate GPUs, no port conflict.
#
# Warm start: if a stopped `qwen-small` container exists with the SAME image + command,
# we `docker start` it — the in-container torch.compile cache survives, saving ~45s.
# If the image or command changed, the old container is replaced with a fresh one.
set -euo pipefail

IMAGE=rocm/vllm:rocm10.1.0_ubuntu24.04_py3.14-pytorch_2.13.0_vllm-0.29.0
# Env vars set at docker run — MUST stay in sync with the docker run below.
ENV_VARS=("HIP_VISIBLE_DEVICES=1" "VLLM_NO_USAGE_STATS=1" "HF_HOME=/app/models")
# Canonical command — MUST stay in sync with the docker run below.
CMD=(vllm serve Qwen/Qwen3-14B-AWQ \
  --served-model-name Qwen3.8 \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 40960 --kv-cache-dtype fp8 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --reasoning-parser qwen3 \
  --gpu-memory-utilization 0.94 --max-num-seqs 2 --enforce-eager --enable-chunked-prefill)

launch_fresh() {
  docker rm -f qwen-small 2>/dev/null || true
  docker run -d --name qwen-small \
    --device /dev/kfd --device /dev/dri \
    --network=host --ipc=host \
    --group-add=video --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
    -e HIP_VISIBLE_DEVICES=1 \
    -e VLLM_NO_USAGE_STATS=1 -e HF_HOME="/app/models" \
    -v /home/j/.cache/huggingface:/app/models \
    "$IMAGE" "${CMD[@]}"
  echo "qwen-small starting on 9070 port 8001 (log: /home/j/logs/vllm_small.log)"
}

if docker ps -q -f name=qwen-small | grep -q .; then
  echo "qwen-small already running"
  exit 0
fi

if docker ps -aq -f name=qwen-small | grep -q .; then
  # Stopped container exists — reuse it if image + command + env still match.
  existing_cmd=$(docker inspect --format '{{range .Config.Cmd}}{{.}} {{end}}' qwen-small)
  existing_cmd="${existing_cmd% }"  # inspect format adds a trailing space
  existing_image=$(docker inspect --format '{{.Image}}' qwen-small)
  expected_image=$(docker image inspect --format '{{.Id}}' "$IMAGE")
  existing_env=$(docker inspect --format '{{range .Config.Env}}{{.}}
{{end}}' qwen-small)
  env_ok=true
  for ev in "${ENV_VARS[@]}"; do
    if ! printf '%s\n' "$existing_env" | grep -qxF -- "$ev"; then
      env_ok=false
      break
    fi
  done
  if [ "$existing_cmd" = "${CMD[*]}" ] && [ "$existing_image" = "$expected_image" ] && [ "$env_ok" = true ]; then
    docker start qwen-small
    echo "qwen-small started (warm container — compile cache kept, ~45s faster)"
  else
    echo "qwen-small container is stale (image/command/env changed) — replacing"
    launch_fresh
  fi
else
  launch_fresh
fi

mkdir -p /home/j/logs
pkill -f "docker logs -f qwen-small" 2>/dev/null || true
nohup docker logs -f qwen-small >> /home/j/logs/vllm_small.log 2>&1 &
