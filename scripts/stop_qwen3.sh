#!/bin/bash

if pgrep -f "vllm serve" > /dev/null; then
    echo "Stopping the vLLM service..."
    pkill -f "vllm serve"
    sleep 2
    if pgrep -f "vllm serve" > /dev/null; then
        echo "Force killing..."
        pkill -9 -f "vllm serve"
    fi
    echo "Service stopped"
else
    echo "vLLM service not running"
fi
