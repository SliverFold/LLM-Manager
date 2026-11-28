#!/usr/bin/env bash
# Uninstall Strata: stop + remove all strata-* containers, remove the Docker
# image. The terminal CLI is left in place (it is small and harmless); remove
# it manually if wanted (see the output note).
set -euo pipefail

echo "=== Strata uninstall $(date) ==="

# 1) Stop + remove containers (2-minute grace so the model unloads cleanly)
for c in $(docker ps -a --filter "name=strata-" --format '{{.Names}}'); do
    echo "stopping container $c"
    docker stop --time 120 "$c" 2>/dev/null || true
    docker rm "$c" 2>/dev/null || true
done

# 2) Remove the Docker image
docker rmi "ghcr.io/niko1221/strata:0.2.20-rocm-gfx120x" 2>/dev/null || true

# 3) Note about the CLI (left in place)
if command -v strata >/dev/null 2>&1; then
    echo "terminal CLI still at $(command -v strata) — remove manually if unwanted"
fi

echo "=== Strata uninstall done ==="
