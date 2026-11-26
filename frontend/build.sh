#!/usr/bin/env bash
# Build the Next.js frontend and deploy it to the standalone server.
#
# Next.js `output: 'standalone'` produces .next/standalone/server.js but does
# NOT copy the static assets (.next/static) or public/ into the standalone
# tree. The systemd service (vllm-manager-frontend) runs from .next/standalone,
# so without this copy the CSS/JS 404 and the UI shows a white screen.
#
# This script does the full build + copy + restart in one step.
set -euo pipefail

cd "$(dirname "$0")"   # the frontend/ dir

echo "==> next build"
npx next build

echo "==> copying static assets into the standalone tree"
mkdir -p .next/standalone/.next
cp -r .next/static .next/standalone/.next/static
if [ -d public ]; then
  cp -r public .next/standalone/public
fi

echo "==> restarting frontend service"
systemctl --user restart vllm-manager-frontend.service

sleep 4
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/")
echo "==> frontend HTTP $code"
[ "$code" = "200" ] && echo "OK" || echo "FAILED (expected 200)"
