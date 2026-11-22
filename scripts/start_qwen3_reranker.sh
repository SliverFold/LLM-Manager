#!/bin/bash

# Activate the conda environment
source /root/miniconda3/etc/profile.d/conda.sh
conda activate base

MODEL_PATH="/root/models/qwen3-reranker/Qwen3-Reranker-8B"
LOG_FILE="/root/logs/vllm_reranker.log"
PORT=8012

# Check if a reranker service is already running
if pgrep -f "vllm serve.*Reranker" > /dev/null; then
    echo "Qwen3-Reranker service already running"
    curl -s http://localhost:$PORT/v1/models | python3 -m json.tool
    exit 0
fi

echo "Starting Qwen3-Reranker-8B..."
CUDA_VISIBLE_DEVICES=0 nohup vllm serve $MODEL_PATH \
    --served-model-name Qwen3-Reranker-8B \
    --port $PORT \
    --host 0.0.0.0 \
    --gpu-memory-utilization 0.4 \
    --max-model-len 8192 \
    --hf_overrides '{"architectures": ["Qwen3ForSequenceClassification"],"classifier_from_token": ["no", "yes"],"is_original_qwen3_reranker": true}' \
    > $LOG_FILE 2>&1 &

echo "Service starting, log: $LOG_FILE"
echo "Service starting in the background, check status later"
