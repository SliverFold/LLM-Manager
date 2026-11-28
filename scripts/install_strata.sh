#!/usr/bin/env bash
# Install Strata: pull the AMD Docker image (prebuilt engine for R9700 + RX 9070,
# both gfx1201) + install the terminal CLI (strata launch/monitor/connect).
# Idempotent: re-running updates the image and refreshes the CLI.
set -euo pipefail

IMAGE="ghcr.io/niko1221/strata"
TAG="${1:-0.2.20-rocm-gfx120x}"

echo "=== Strata install $(date) ==="

# 1) Docker image (the engine is prebuilt inside; models download on first start)
echo "--- pulling $IMAGE:$TAG ---"
docker pull "$IMAGE:$TAG"

# 2) Terminal CLI (no admin rights; installs into the home folder)
echo "--- installing terminal CLI ---"
if command -v strata >/dev/null 2>&1; then
    echo "strata CLI already present: $(command -v strata)"
    # Refresh it anyway (the installer is idempotent and upgrades in place).
    curl -fsSL --connect-timeout 15 --max-time 120 \
        https://github.com/Niko1221/Strata/releases/latest/download/install.sh \
        -o /tmp/strata-install.sh && sh /tmp/strata-install.sh || \
        echo "CLI refresh failed (existing CLI kept)"
else
    curl -fsSL --connect-timeout 15 --max-time 120 \
        https://github.com/Niko1221/Strata/releases/latest/download/install.sh \
        -o /tmp/strata-install.sh && sh /tmp/strata-install.sh
fi

# 3) Verify
echo "--- verifying ---"
docker images "$IMAGE" --format 'image: {{.Tag}}'
STRATA_BIN="$(command -v strata || echo ~/.local/bin/strata)"
"$STRATA_BIN" --version || echo "strata CLI not on PATH yet (open a new shell)"

echo "=== Strata install done ==="
