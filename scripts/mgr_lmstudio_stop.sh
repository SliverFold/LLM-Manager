#!/usr/bin/env bash
# vllm-model-manager: stop the LM Studio brain (9070).
# Stops the server, kills the llama-server backend, and shuts down the headless daemon.
# Works with both the GUI desktop app and the headless llmster daemon.
set -euo pipefail

LMS=~/.lmstudio/bin/lms

# Stop the server (unloads any loaded models with it)
"$LMS" server stop 2>/dev/null || true

# Kill the llama-server backend process (serves the model on a random port).
# This is separate from the LM Studio server and is NOT killed by `lms server stop`.
# Match the model path to avoid killing other llama-server processes (e.g. small brain).
LLAMA_PIDS=$(pgrep -f "llama-server.*\.lmstudio/models" 2>/dev/null || true)
if [ -n "$LLAMA_PIDS" ]; then
    echo "$LLAMA_PIDS" | xargs kill 2>/dev/null || true
fi

# Shut down the headless daemon (or close the GUI app in GUI mode)
"$LMS" daemon down 2>/dev/null || true

# Also kill the GUI app if it's still running (GUI mode fallback)
GUI_PIDS=$(ps aux | grep "lm-studio --run-as-service" | grep -v grep | awk '{print $2}' || true)
if [ -n "$GUI_PIDS" ]; then
    echo "$GUI_PIDS" | xargs kill -9 2>/dev/null || true
fi

echo "LM Studio stopped (server + daemon + backend)"
