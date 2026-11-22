#!/bin/bash

if pgrep -f "vllm serve.*Reranker" > /dev/null; then
    echo "Stopping the Qwen3-Reranker service..."
    pkill -f "vllm serve.*Reranker"
    sleep 2
    if pgrep -f "vllm serve.*Reranker" > /dev/null; then
        echo "Force killing..."
        pkill -9 -f "vllm serve.*Reranker"
    fi
    echo "Qwen3-Reranker service stopped"
else
    echo "Qwen3-Reranker service not running"
fi
