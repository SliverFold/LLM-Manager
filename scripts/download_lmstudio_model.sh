#!/usr/bin/env bash
# vllm-model-manager: download an LM Studio model (GGUF) from Hugging Face.
#
# Usage: download_lmstudio_model.sh <repo> <file> <slug>
#   repo:  HF repo name (e.g. Qwen/Qwen3-8B-GGUF)
#   file:  the specific GGUF file to download (e.g. Qwen3-8B-Q4_K_M.gguf)
#   slug:  model slug (used as the download dir name)
#
# Idempotent: re-running is a no-op when the file is already present.
set -euo pipefail
log() { echo "[$(date '+%Y-%d %H:%M:%S')] $*"; }

REPO="${1:?repo required}"
FILE="${2:?file required}"
SLUG="${3:?slug required}"

# LM Studio models dir (where `lms load` looks).
MODELS_DIR="${HOME}/.lmstudio/models"
DEST="$MODELS_DIR/$SLUG"
mkdir -p "$DEST"

# Resolve a working `hf` (Hugging Face CLI). Prefer the global `hf`; otherwise
# create a throwaway venv (system Python on Arch/CachyOS is PEP 668 externally
# managed, so a plain `pip install` fails).
if command -v hf >/dev/null 2>&1; then
  HF="hf"
elif python3 -c 'import huggingface_hub' >/dev/null 2>&1; then
  HF="python3 -m huggingface_hub"
else
  log "No 'hf' on PATH — creating a venv for the download…"
  HF_VENV="$HOME/.cache/paiton-hf-venv"
  python3 -m venv "$HF_VENV" || { log "ERROR: could not create a venv (install python3-venv)"; exit 1; }
  "$HF_VENV/bin/pip" install -q huggingface_hub || { log "ERROR: could not install huggingface_hub in the venv"; exit 1; }
  HF="$HF_VENV/bin/python -m huggingface_hub"
fi

log "Downloading $REPO/$FILE → $DEST"
$HF download "$REPO" --include "$FILE" --local-dir "$DEST"

log "LM Studio model $SLUG ready at $DEST/$FILE"
log "Load with: lms load $DEST/$FILE"
