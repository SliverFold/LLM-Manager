#!/bin/bash

# Find and stop the Qwen3-Thinking service
echo "Looking for the Qwen3-Thinking service..."

PID=$(pgrep -f "vllm serve.*Qwen3-Next-80B-A3B-Thinking")

if [ -z "$PID" ]; then
    echo "No running Qwen3-Thinking service found"
    exit 0
fi

echo "Found service process: $PID"
echo "Stopping the service..."

kill $PID

# Wait for the process to end
for i in {1..30}; do
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "Qwen3-Thinking service stopped"
        exit 0
    fi
    sleep 1
done

echo "Process did not exit cleanly, force killing..."
kill -9 $PID
echo "Qwen3-Thinking service force stopped"
