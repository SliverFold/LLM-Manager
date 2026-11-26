#!/usr/bin/env bash
# vllm-model-manager: install Hermes Agent + enable the webapp (browser UI on :9120)
# Idempotent: on a machine that already has Hermes it verifies/updates it,
# enables the webapp, and rebuilds the webapp bundle.
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

if ! command -v hermes >/dev/null 2>&1; then
  log "Installing Hermes Agent…"
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
else
  log "Hermes already installed — updating…"
  hermes update || log "WARNING: hermes update failed (continuing with the installed version)"
fi

# The installer may put hermes on a PATH entry this shell does not have yet.
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$HOME/.hermes/hermes-agent/.hermes/bin:$PATH"
command -v hermes >/dev/null 2>&1 || { log "ERROR: hermes not found after install"; exit 1; }
log "Hermes: $(hermes --version 2>&1 | head -1)"

log "Enabling webapp (browser UI)…"
hermes config set webapp.enabled true

log "Building webapp bundle…"
hermes webapp --build-only || hermes webapp --build-only --force-build || log "WARNING: webapp build failed — run 'hermes webapp' manually later"

log "Hermes + webapp installed."
log "Web UI: http://127.0.0.1:9120/  (a gateway restart loads the webapp)"
