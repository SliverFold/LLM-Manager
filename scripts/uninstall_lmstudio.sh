#!/usr/bin/env bash
# vllm-model-manager: uninstall LM Studio + Beledarian Suite.
#
# Removes:
#   - the Beledarian Suite clone (~/beledarians-lm-studio-tools)
#   - the LM Studio app, however it was installed:
#       AppImage  -> the .AppImage file
#       curl|bash -> the lms CLI in ~/.lmstudio/bin
#       .deb      -> needs sudo; the script prints the manual command
#
# NEVER touches:
#   - your models (~/.lmstudio/models)
#   - your settings (~/.config/LM Studio)
#   - caches (~/.cache)
#   - the plugin's saved state (~/.beledarians-llm-toolbox)
#
# Usage: uninstall_lmstudio.sh
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# --- 1. Beledarian Suite (the plugin clone) ---
PLUGIN_DIR="$HOME/beledarians-lm-studio-tools"
if [ -d "$PLUGIN_DIR" ]; then
  log "Removing Beledarian Suite clone $PLUGIN_DIR…"
  rm -rf "$PLUGIN_DIR"
  log "(plugin state at ~/.beledarians-llm-toolbox is kept — delete it manually if you want a full wipe)"
else
  log "Beledarian Suite clone not present"
fi

# --- 2. LM Studio app (any common install location) ---
removed=0

# AppImage in common spots
for cand in "$HOME/Applications/LM-Studio.AppImage" \
            "$HOME/Downloads/LM-Studio.AppImage" \
            "$HOME/LM-Studio.AppImage" \
            "/opt/LM Studio/LM-Studio.AppImage"; do
  if [ -f "$cand" ]; then
    log "Removing AppImage $cand…"
    rm -f "$cand"
    removed=1
  fi
done

# .deb install (Ubuntu/Debian/Mint) — needs sudo, so print the command
if [ -d "/opt/LM Studio" ]; then
  log "Found a .deb install at /opt/LM Studio — remove it manually with:"
  log "  sudo apt remove lm-studio"
fi

# curl|bash install (the lms CLI) — remove the CLI, keep the models
if [ -d "$HOME/.lmstudio/bin" ]; then
  log "Removing lms CLI $HOME/.lmstudio/bin… (models in ~/.lmstudio/models are kept)"
  rm -rf "$HOME/.lmstudio/bin"
  removed=1
fi

if [ "$removed" = "0" ]; then
  log "No LM Studio app install found (AppImage, /opt/LM Studio, ~/.lmstudio/bin)"
fi

log "Done."
