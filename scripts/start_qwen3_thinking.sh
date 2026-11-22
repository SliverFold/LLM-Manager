#!/bin/bash

# Activate the conda environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate base

MODEL_PATH="/root/models/Qwen3-Next-80B-A3B-Thinking-FP8"
LOG_FILE="/root/logs/vllm_qwen3_thinking.log"
PORT=8001
API_KEY="2db484b2456c8427ed2641c144dd1c95e703b9345869f8964af8a9bc0395736d"

# Check the model directory exists
if [ ! -d "$MODEL_PATH" ]; then
    echo "Error: model directory not found: $MODEL_PATH"
    echo "Download the model first"
    exit 1
fi

# Check if a Qwen3-Thinking service is already running
if pgrep -f "vllm serve.*Qwen3-Next-80B-A3B-Thinking" > /dev/null; then
    echo "Qwen3-Thinking service already running"
    curl -s http://localhost:$PORT/v1/models | python3 -m json.tool
    exit 0
fi

# Create the log directory
mkdir -p /root/logs

echo "Starting Qwen3-Next-80B-A3B-Thinking-FP8..."
CUDA_VISIBLE_DEVICES=5,6 nohup vllm serve $MODEL_PATH \
    --tensor-parallel-size 2 \
    --port $PORT \
    --host 0.0.0.0 \
    --api-key $API_KEY \
    --dtype float16 \
    --max-model-len 8192 \
    > $LOG_FILE 2>&1 &

echo "Service starting, log: $LOG_FILE"
echo "Service starting in the background, check status later"
