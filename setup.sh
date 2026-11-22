#!/usr/bin/env bash
# LLM Model Manager — first-run installer
# Run once on a fresh machine (e.g. after a wipe): installs the Python venv,
# builds the frontend, and installs + starts the systemd user services.
# Usage: ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"

echo "[1/4] Python venv + dependencies"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

echo "[2/4] Frontend build (Next.js standalone)"
cd frontend
npm install
npm run build
# Next.js standalone does NOT copy static/public into the bundle — do it ourselves
cp -rf .next/static .next/standalone/.next/static
cp -rf public .next/standalone/public
cd "$REPO"

echo "[3/4] systemd user units"
mkdir -p "$HOME/.config/systemd/user"
sed "s|@REPO@|$REPO|g" vllm-manager-backend.service.user > "$HOME/.config/systemd/user/vllm-manager-backend.service"
sed "s|@REPO@|$REPO|g" vllm-manager-frontend.service.user > "$HOME/.config/systemd/user/vllm-manager-frontend.service"
systemctl --user daemon-reload

echo "[4/4] Enable + start services"
systemctl --user enable --now vllm-manager-backend.service vllm-manager-frontend.service
# Keep the services running after logout (user units stop at logout by default)
loginctl enable-linger 2>/dev/null || true

echo
echo "Done. UI: http://127.0.0.1:3000  (backend :9000)"
echo "Check with: systemctl --user status vllm-manager-frontend"
