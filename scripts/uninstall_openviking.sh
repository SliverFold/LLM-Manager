#!/usr/bin/env bash
# vllm-model-manager: uninstall OpenViking (Hermes long-term memory).
#
# Reverses install_openviking.sh:
#   1. stops + disables + removes the two systemd user services
#   2. removes the Hermes openviking plugin
#   3. resets the Hermes memory provider to built-in only
#   4. removes the OPENVIKING_* env vars from ~/.hermes/.env
#   5. removes ~/.openviking — ONLY if remove_workspace=true (arg 1),
#      otherwise the memory data is kept (it is the user's memories).
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

REMOVE_WORKSPACE="${1:-false}"
OV_HOME="$HOME/.openviking"

log "=== OpenViking uninstall ==="

# 1. Services
log "Stopping OpenViking services …"
systemctl --user stop openviking-server.service openviking-embed.service 2>/dev/null || true
systemctl --user disable openviking-server.service openviking-embed.service 2>/dev/null || true
systemctl --user remove openviking-server.service openviking-embed.service 2>/dev/null || true
systemctl --user daemon-reload
log "Services removed"

# 2. Hermes plugin
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$HOME/.hermes/hermes-agent/.hermes/bin:$PATH"
command -v hermes >/dev/null 2>&1 || { log "ERROR: hermes not found"; exit 1; }

PLUGINS_LIST=$(hermes plugins list 2>/dev/null || true)
if echo "$PLUGINS_LIST" | grep -q 'openviking'; then
  log "Removing Hermes openviking plugin …"
  hermes plugins remove openviking
else
  log "Hermes openviking plugin not present"
fi

# 3. Memory provider → built-in only
if grep -q 'provider: openviking' "$HOME/.hermes/config.yaml" 2>/dev/null; then
  log "Resetting Hermes memory provider to built-in only …"
  hermes memory off
else
  log "Hermes memory provider not openviking (leaving as-is)"
fi

# 4. Env vars
if [ -f "$HOME/.hermes/.env" ]; then
  if grep -q '^OPENVIKING_' "$HOME/.hermes/.env"; then
    log "Removing OPENVIKING_* from ~/.hermes/.env …"
    sed -i '/^OPENVIKING_/d' "$HOME/.hermes/.env"
  else
    log "No OPENVIKING_* vars in .env"
  fi
fi

# 5. Data
if [ "$REMOVE_WORKSPACE" = "true" ]; then
  log "Removing $OV_HOME (including all memories) …"
  rm -rf "$OV_HOME"
else
  log "Keeping $OV_HOME (your memories) — remove it manually if you want them gone"
fi

log "=== OpenViking uninstall complete ==="
log "Restart the Hermes gateway to drop the memory provider (button in the UI)."
