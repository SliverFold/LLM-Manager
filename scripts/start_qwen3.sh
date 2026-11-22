#!/bin/bash

# Activate the conda environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate base

MODEL_PATH="/root/models/Qwen3-Next-80B-A3B-Instruct"
LOG_FILE="/root/logs/vllm_qwen3.log"
PORT=8000
API_KEY="2db484b2456c8427ed2641c144dd1c95e703b9345869f8964af8a9bc0395736d"

# Check if a Qwen3 service is already running
if pgrep -f "vllm serve.*Qwen3-Next-80B" > /dev/null; then
    echo "Qwen3 service already running"
    curl -s http://localhost:$PORT/v1/models | python3 -m json.tool
    exit 0
fi

echo "Starting Qwen3-Next-80B-A3B-Instruct..."
CUDA_VISIBLE_DEVICES=1,2,3,4 nohup vllm serve $MODEL_PATH \
    --tensor-parallel-size 4 \
    --port $PORT \
    --host 0.0.0.0 \
    --api-key $API_KEY \
    > $LOG_FILE 2>&1 &

echo "Service starting, log: $LOG_FILE"
echo "Service starting in the background, check status later"
