#!/usr/bin/env bash
# vllm-model-manager: start the LM Studio brain (Qwen3.8-27B Q2, 9070).
# Uses the headless llmster daemon (no GUI). Starts the daemon, server, and loads the model.
set -euo pipefail

LMS=~/.lmstudio/bin/lms
PORT="${PORT:-45987}"

# Ensure the temp dir exists (LM Studio's mkdtemp fails if it's missing)
mkdir -p ~/.lmstudio/.internal/temp

# Check if the server is already running (match "running" but not "not running")
if "$LMS" server status 2>&1 | grep -qi "running" && ! "$LMS" server status 2>&1 | grep -qi "not running"; then
    echo "LM Studio server already running"
    # Load the model if not already loaded
    if "$LMS" ps 2>&1 | grep -qi "No models"; then
        "$LMS" load "qwen3.8-27b@iq2_xxs" 2>&1 || echo "Model load failed"
    fi
    exit 0
fi

# Start the headless daemon (no GUI)
"$LMS" daemon up
echo "LM Studio daemon starting (headless)"

# Start the server (with CORS enabled so the browser can connect)
"$LMS" server start -p "$PORT" --cors
echo "LM Studio server starting on port $PORT"

# Load the model
"$LMS" load "qwen3.8-27b@iq2_xxs" 2>&1 || echo "Model load failed"
echo "LM Studio ready on port $PORT"
