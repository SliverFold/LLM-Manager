#!/usr/bin/env bash
# LLM Model Manager — uninstall (reverses setup.sh)
#
# Stops + disables the two systemd user services and removes their unit
# files. It does NOT delete the repo itself (your clone, config/, and
# services.json live here) — remove the folder manually for a full wipe.
# Installed AI tools (vLLM venvs, Hermes, ComfyUI, LM Studio) and models
# are NOT touched.
#
# Usage: ./uninstall_manager.sh [--remove-venv]
set -euo pipefail
cd "$(dirname "$0")"

REMOVE_VENV=false
[ "${1:-}" = "--remove-venv" ] && REMOVE_VENV=true

echo "[1/3] Stop + disable services"
systemctl --user stop vllm-manager-frontend.service vllm-manager-backend.service || true
systemctl --user disable vllm-manager-frontend.service vllm-manager-backend.service || true

echo "[2/3] Remove systemd user units"
rm -f "$HOME/.config/systemd/user/vllm-manager-backend.service" \
      "$HOME/.config/systemd/user/vllm-manager-frontend.service"
systemctl --user daemon-reload

echo "[3/3] Python venv"
if [ "$REMOVE_VENV" = true ] && [ -d .venv ]; then
  rm -rf .venv
  echo "Removed .venv"
else
  echo "Keeping .venv (pass --remove-venv to delete it)"
fi

echo
echo "Done. The repo itself is untouched — delete it manually for a full wipe."
