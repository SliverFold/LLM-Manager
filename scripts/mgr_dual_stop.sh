#!/usr/bin/env bash
# vllm-model-manager: stop the dual-card setup (Qwen3.8-27B NVFP4, 8002)
set -euo pipefail
pkill -f "docker logs -f vllm-qwen38" 2>/dev/null || true
docker stop vllm-qwen38 2>/dev/null || true
docker rm -f vllm-qwen38 2>/dev/null || true
echo "vllm-qwen38 stopped"
