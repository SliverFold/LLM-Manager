#!/usr/bin/env bash
# vllm-model-manager: stop the small brain (9B, 9070)
# NOTE: we do NOT `docker rm` here — the container is kept (stopped) so the next
# start reuses it and the in-container torch.compile cache survives (~45s saved
# per start). The container holds no VRAM while stopped.
set -euo pipefail
pkill -f "docker logs -f qwen-small" 2>/dev/null || true
docker stop qwen-small 2>/dev/null || true
echo "qwen-small stopped (container kept for a warm start)"
