#!/usr/bin/env bash
# vllm-model-manager: install LM Studio + Beledarian's LM Studio Toolbox (agentic AI suite)
#
# Portable across Linux distros (Arch, Ubuntu, Fedora, CachyOS, …):
#   1. Detect an existing LM Studio install (lms CLI, AppImage, /opt, flatpak)
#   2. If missing: official one-liner (curl | bash), with AppImage fallback
#   3. Install/refresh the Beledarian Suite plugin via `lms clone`
#
# Idempotent: re-running updates in place instead of re-downloading.
#
# Usage: install_lmstudio.sh
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

LMS_HOME="$HOME/.lmstudio"
LMS_BIN="$LMS_HOME/bin/lms"
PLUGIN_REPO="beledarian/beledarians-lm-studio-tools"
PLUGIN_DIR="$HOME/beledarians-lm-studio-tools"

# --- 1. Find an existing LM Studio install (any common location) ---
find_lms() {
  # 1) on PATH
  local p
  p="$(command -v lms || true)"
  [ -n "$p" ] && { echo "$p"; return 0; }
  # 2) official CLI location (curl|bash installer)
  [ -x "$LMS_BIN" ] && { echo "$LMS_BIN"; return 0; }
  # 3) AppImage in common spots
  for cand in "$HOME/Applications/LM-Studio.AppImage" \
              "$HOME/Downloads/LM-Studio.AppImage" \
              "$HOME/LM-Studio.AppImage" \
              "/opt/LM Studio/LM-Studio.AppImage"; do
    [ -f "$cand" ] && { echo "$cand"; return 0; }
  done
  # 4) .deb install (Ubuntu/Debian/Mint)
  [ -d "/opt/LM Studio" ] && { echo "/opt/LM Studio"; return 0; }
  return 1
}

LMS="$(find_lms || true)"

if [ -n "$LMS" ]; then
  log "LM Studio already present: $LMS — skipping app install"
else
  log "Installing LM Studio via the official installer (curl | bash)…"
  if curl -fsSL https://lmstudio.ai/install.sh | bash; then
    LMS="$(find_lms || true)"
    [ -n "$LMS" ] || log "WARNING: official installer finished but no install found — continuing to the Beledarian Suite step"
  else
    log "Official installer failed — falling back to the AppImage download…"
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64|amd64) ARCH=x64 ;;
      aarch64|arm64) ARCH=arm64 ;;
      *) ARCH=x64 ;;
    esac
    mkdir -p "$HOME/Applications"
    log "Downloading LM Studio AppImage (${ARCH})…"
    curl -fL "https://lmstudio.ai/download/latest/linux/${ARCH}?format=AppImage" \
      -o "$HOME/Applications/LM-Studio.AppImage"
    chmod +x "$HOME/Applications/LM-Studio.AppImage"
    LMS="$HOME/Applications/LM-Studio.AppImage"
  fi
fi

# --- 2. Beledarian Suite (agentic AI toolbox plugin) ---
# `lms clone` is the official install path and only needs the CLI, not the GUI.
LMSCLI="$(find_lms || true)"
if [ -z "$LMSCLI" ]; then
  log "ERROR: lms CLI not found after install — cannot install the Beledarian Suite"
  exit 1
fi
log "lms CLI: $LMSCLI ($("$LMSCLI" --version 2>/dev/null || true))"

if [ -d "$PLUGIN_DIR" ] && [ -f "$PLUGIN_DIR/manifest.json" ]; then
  if [ -d "$PLUGIN_DIR/.git" ]; then
    log "Beledarian Suite present (git checkout) — updating (git pull)…"
    git -C "$PLUGIN_DIR" pull || log "WARNING: git pull failed (continuing with the existing checkout)"
  else
    log "Beledarian Suite already present (not a git checkout) — leaving it as-is"
    log "Manual update if needed: rm -rf $PLUGIN_DIR && $LMSCLI clone $PLUGIN_REPO"
  fi
elif [ -d "$PLUGIN_DIR" ]; then
  log "WARNING: $PLUGIN_DIR exists but has no manifest.json — lms clone will refuse; leaving it alone"
else
  log "Installing the Beledarian Suite: lms clone $PLUGIN_REPO"
  "$LMSCLI" clone "$PLUGIN_REPO"
fi

# --- 3. Verify ---
[ -f "$PLUGIN_DIR/manifest.json" ] || { log "ERROR: plugin manifest missing at $PLUGIN_DIR"; exit 1; }
REV="$(sed -n 's/.*"revision":[[:space:]]*\([0-9]*\).*/\1/p' "$PLUGIN_DIR/manifest.json" || true)"
log "Beledarian Suite installed: $PLUGIN_DIR (revision ${REV:-?})"
log "Done — restart LM Studio to load the plugin (or serve headless via the lms server)."
