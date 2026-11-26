#!/usr/bin/env bash
# vllm-model-manager: uninstall ComfyUI (venv, optionally the checkout).
#
# Always removes the venv (the pip-installed dependencies). With
# remove_checkout=true it also deletes the whole checkout — including
# custom nodes, outputs, and configs — so the UI confirms with the user
# first.
#
# Usage: uninstall_comfyui.sh <dir> [remove_checkout=true|false]
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

dir="${1:?usage: uninstall_comfyui.sh <dir> [remove_checkout]}"
remove_checkout="${2:-false}"
dir="$(eval echo "$dir")"

if [ ! -d "$dir" ]; then
  log "ERROR: no ComfyUI at $dir"
  exit 1
fi

if [ -d "$dir/.venv" ]; then
  log "Removing ComfyUI venv $dir/.venv…"
  rm -rf "$dir/.venv"
else
  log "No venv at $dir/.venv — nothing to remove there"
fi

if [ "$remove_checkout" = "true" ]; then
  log "Removing ComfyUI checkout $dir…"
  rm -rf "$dir"
fi
log "Done."
