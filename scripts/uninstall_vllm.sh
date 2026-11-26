#!/usr/bin/env bash
# vllm-model-manager: uninstall vLLM from a venv (optionally remove the venv).
#
# Safe: only touches the given venv. The big brain (paiton vLLM on :8000) is
# a separate system install (/usr/local/bin/paiton-qwen38) and is NOT affected.
#
# Usage: uninstall_vllm.sh <venv> [remove_venv=true|false]
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

venv="${1:?venv path required}"
remove_venv="${2:-false}"

if [ ! -d "$venv" ]; then
  log "ERROR: no venv at $venv"
  exit 1
fi
venv="$(cd "$venv" && pwd)"

log "Uninstalling vLLM from $venv…"
if [ -x "$venv/bin/pip" ]; then
  "$venv/bin/pip" uninstall -y vllm || log "WARNING: pip uninstall vllm failed (already removed?)"
else
  log "WARNING: no pip in $venv — nothing to uninstall"
fi

if [ "$remove_venv" = "true" ]; then
  log "Removing venv $venv…"
  rm -rf "$venv"
fi
log "Done."
