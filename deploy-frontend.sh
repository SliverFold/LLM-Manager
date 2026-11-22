#!/bin/bash
# Deploy the LLM Manager frontend: build -> copy static assets -> restart service.
# The asset copy is REQUIRED for Next.js standalone builds (the standalone dir
# does NOT include .next/static/ or public/ — without it the page 404s on JS/CSS).
set -e
cd "$(dirname "$0")/frontend"

echo "==> Building the Next.js frontend..."
npm run build

echo "==> Copying static assets into the standalone dir (required)..."
mkdir -p .next/standalone/.next
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public

echo "==> Restarting the frontend service..."
systemctl --user restart vllm-manager-frontend
sleep 4

echo "==> Verifying..."
for url in "http://127.0.0.1:3000" "http://127.0.0.1:3000/api/services" "http://127.0.0.1:3000/api/gpu"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    echo "    $url -> HTTP $code"
done
echo "==> Done. Hard-refresh the browser (Ctrl+Shift+R) to bust the cache."
