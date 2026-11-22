#!/usr/bin/env bash
# vllm-model-manager: stop the big brain (Qwen3.8 paiton)
set -euo pipefail
pkill -f "docker logs -f paiton-qwen38" 2>/dev/null || true
bash /home/j/Desktop/AI/paiton-qwen38.sh stop
