#!/usr/bin/env bash
# Download a Strata model into a service's volume WITHOUT leaving a service behind.
#
# A temporary container (no port mapping, no API key) runs `strata launch` with the
# chosen family/model. We watch its log and stop it as soon as the model files are
# downloaded and verified ("...is ready.") — BEFORE the engine loads the model into
# VRAM, so a service already running on the same card is never touched. The model
# files stay in the named volume; the real service (added via Add Service) mounts
# the same volume and loads instantly ("The model files are already on this computer").
#
# Usage: strata_download_model.sh <family> <model> <volume> [service_key]
#
# service_key: the running Strata service that uses this volume (container
# name = service key). Strata allows only ONE engine per volume ("A model is
# already running"), so the service is stopped for the download and restarted
# afterwards — no matter how the download ends. The user's service is always
# brought back up.
set -euo pipefail

FAMILY="$1"
MODEL="$2"
VOLUME="$3"
SERVICE_KEY="${4:-}"
SCRIPTS_DIR="/home/j/Desktop/AI/vllm-model-manager-/scripts"

# Stop the service on this volume (if given and running) before the download.
if [ -n "$SERVICE_KEY" ]; then
    if docker inspect "$SERVICE_KEY" >/dev/null 2>&1; then
        echo "Stopping service $SERVICE_KEY for the download (it will be restarted after)..."
        docker stop --time 60 "$SERVICE_KEY" >/dev/null 2>&1 || true
    fi
fi

# Bring the service back up on any exit (success, failure, timeout, Ctrl-C).
restart_service() {
    if [ -n "$SERVICE_KEY" ]; then
        echo "Restarting service $SERVICE_KEY..."
        bash "$SCRIPTS_DIR/generated/mgr_${SERVICE_KEY}_start.sh" || echo "Service restart FAILED — start it manually"
    fi
}
trap restart_service EXIT

IMAGE="ghcr.io/niko1221/strata"
TAG=$(docker images "$IMAGE" --format '{{.Tag}}' | head -1)
if [ -z "$TAG" ]; then
    echo "Strata image not installed — install Strata first"
    exit 1
fi

NAME="strata-download-${FAMILY}-${MODEL}"
docker rm -f "$NAME" 2>/dev/null || true
RENDER_GID="$(getent group render | cut -d: -f3)"
GROUP_ARGS=(--group-add video)
[ -n "$RENDER_GID" ] && GROUP_ARGS+=(--group-add "$RENDER_GID")

echo "Starting temporary download container (no ports, no service)..."
docker run -d --name "$NAME" \
  --device /dev/kfd --device /dev/dri \
  "${GROUP_ARGS[@]}" \
  --ulimit memlock=-1:-1 --shm-size 2g \
  -v "$VOLUME":/data \
  -e FAMILY="$FAMILY" \
  -e MODEL="$MODEL" \
  -e PRESET=strata-download \
  "$IMAGE:$TAG"

echo "Waiting for the download to finish and verify (this can be large)..."
# 5s x 480 = up to 4 hours; big downloads on a slow line are the norm.
# Polling fast matters: on the "model already in volume" path the launcher
# verifies the files and then starts loading the engine into VRAM — we must
# kill the container on "is ready." BEFORE that load can fight a running
# service on the same card for VRAM.
for i in $(seq 1 480); do
    sleep 5
    STATE=$(docker inspect --format '{{.State.Status}}' "$NAME" 2>/dev/null || echo gone)
    if [ "$STATE" = "exited" ] || [ "$STATE" = "gone" ]; then
        echo "Container stopped early:"
        docker logs "$NAME" 2>&1 | tail -25
        docker rm -f "$NAME" 2>/dev/null || true
        exit 1
    fi
    # Two completion paths: a fresh download ends with "<model> is ready."
    # (after download + file verification, BEFORE the engine loads the model —
    # so a service already running on the card is never touched), and a volume
    # that already holds the model ends with "Already serving these choices;
    # nothing was restarted."
    if docker logs "$NAME" 2>&1 | grep -qE "is ready\.|Already serving these choices"; then
        echo "Model downloaded and verified — stopping the temporary container."
        # docker kill (SIGKILL), NOT docker stop: the entrypoint's SIGTERM
        # handler runs `strata launch --stop` on the shared volume's state,
        # which can stop the engine of a service running on the same volume.
        docker kill "$NAME" >/dev/null 2>&1 || true
        docker rm "$NAME" >/dev/null 2>&1 || true
        echo "Download complete: $FAMILY/$MODEL in volume $VOLUME"
        exit 0
    fi
    # Surface the latest progress line (download % / checks) in the job log.
    docker logs "$NAME" 2>&1 | tail -1 | sed 's/^[[:space:]]*//' | sed 's/^/  /'
done

echo "Timed out waiting for the download."
docker logs "$NAME" 2>&1 | tail -25
docker kill "$NAME" >/dev/null 2>&1 || true
docker rm -f "$NAME" 2>/dev/null || true
exit 1
