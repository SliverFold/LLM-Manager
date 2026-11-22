#!/bin/bash

# Activate the conda environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate base

MODEL_PATH="/root/models/PaddleOCR-VL"
LOG_FILE="/root/logs/vllm_paddleocr.log"
PORT=8080

# Check if a PaddleOCR-VL service is already running
if pgrep -f "vllm serve.*PaddleOCR-VL" > /dev/null; then
    echo "PaddleOCR-VL service already running"
    curl -s http://localhost:$PORT/v1/models | python3 -m json.tool
    exit 0
fi

echo "Starting PaddleOCR-VL..."
CUDA_VISIBLE_DEVICES=0 nohup vllm serve $MODEL_PATH \
    --served-model-name PaddleOCR-VL-0.9B \
    --port $PORT \
    --host 0.0.0.0 \
    --trust-remote-code \
    --max-num-batched-tokens 16384 \
    --no-enable-prefix-caching \
    --mm-processor-cache-gb 0 \
    --gpu-memory-utilization 0.4 \
    > $LOG_FILE 2>&1 &

echo "Service starting, log: $LOG_FILE"
echo "Service starting in the background, check status later"
