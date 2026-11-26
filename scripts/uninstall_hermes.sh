#!/usr/bin/env bash
# vllm-model-manager: disable the Hermes webapp (the safe "uninstall").
#
# A full Hermes uninstall would remove the running Hermes Agent (the process
# serving this manager), so we only reverse the webapp enable here. To fully
# remove Hermes, do it manually in a terminal (it will stop the current session).
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$HOME/.hermes/hermes-agent/.hermes/bin:$PATH"
command -v hermes >/dev/null 2>&1 || { log "ERROR: hermes not found"; exit 1; }

log "Disabling Hermes webapp (browser UI on :9120)…"
hermes config set webapp.enabled false
log "Done. (Hermes Agent itself is still installed.)"
