#!/bin/bash

if pgrep -f "vllm serve.*PaddleOCR-VL" > /dev/null; then
    echo "Stopping the PaddleOCR-VL service..."
    pkill -f "vllm serve.*PaddleOCR-VL"
    sleep 2
    if pgrep -f "vllm serve.*PaddleOCR-VL" > /dev/null; then
        echo "Force killing..."
        pkill -9 -f "vllm serve.*PaddleOCR-VL"
    fi
    echo "PaddleOCR-VL service stopped"
else
    echo "PaddleOCR-VL service not running"
fi
