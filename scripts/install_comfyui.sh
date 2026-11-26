#!/usr/bin/env bash
# vllm-model-manager: install ComfyUI (clone + venv + deps)
#
# Idempotent: on a machine that already has ComfyUI it updates the checkout
# (git pull) and refreshes the venv deps instead of re-cloning.
#
# Usage: install_comfyui.sh <dir>
set -euo pipefail
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

COMFY_DIR="${1:?usage: install_comfyui.sh <dir>}"
COMFY_DIR="$(eval echo "$COMFY_DIR")"

# --- 1. Clone ComfyUI (or update an existing checkout) ---
if [ -d "$COMFY_DIR" ] && [ -d "$COMFY_DIR/.git" ]; then
  log "ComfyUI checkout exists — updating (git pull)…"
  git -C "$COMFY_DIR" pull || log "WARNING: git pull failed (continuing with the existing checkout)"
elif [ -d "$COMFY_DIR" ]; then
  log "ComfyUI dir exists (not a git checkout) — using it as-is"
else
  log "Cloning ComfyUI from GitHub…"
  git clone https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR"
fi

# --- 2. venv (Python 3.12 preferred — matches the standard ComfyUI setup) ---
PYBIN=""
for p in python3.12 python3.11 python3.13 python3.14 python3; do
  PYBIN="$(command -v "$p" || true)"
  [ -n "$PYBIN" ] && break
done
[ -n "$PYBIN" ] || { log "ERROR: no python found"; exit 1; }
log "Python: $PYBIN ($("$PYBIN" --version))"

if [ ! -x "$COMFY_DIR/.venv/bin/python" ]; then
  log "Creating venv at $COMFY_DIR/.venv"
  "$PYBIN" -m venv "$COMFY_DIR/.venv"
fi
"$COMFY_DIR/.venv/bin/python" -m pip install -q -U pip setuptools wheel

# --- 3. Dependencies ---
log "Installing ComfyUI dependencies (requirements.txt)…"
"$COMFY_DIR/.venv/bin/pip" install -r "$COMFY_DIR/requirements.txt"

# --- 4. Verify ---
log "Verifying…"
"$COMFY_DIR/.venv/bin/python" -c "import torch; print('torch', torch.__version__)"
log "Done — start ComfyUI with: $COMFY_DIR/.venv/bin/python $COMFY_DIR/main.py"
