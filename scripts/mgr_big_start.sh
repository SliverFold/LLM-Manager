#!/usr/bin/env bash
# vllm-model-manager: start the big brain (Qwen3.8 paiton, R9700, port 8000)
set -euo pipefail
NAME="paiton-qwen38"
LOG="/home/j/logs/vllm_big_start.log"
mkdir -p /home/j/logs
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== mgr_big_start.sh invoked ==="
log "PATH=$PATH"
log "HOME=$HOME"
log "USER=$USER"
log "SHELL=$SHELL"
log "docker: $(docker --version 2>&1 || echo 'docker not found')"
log "container (running): $(docker ps -q -f name=$NAME 2>&1 || echo 'none')"
log "container (all): $(docker ps -aq -f name=$NAME 2>&1 || echo 'none')"

if docker ps -q -f name="$NAME" | grep -q .; then
  log "$NAME already running"
  exit 0
fi
if docker ps -aq -f name="$NAME" | grep -q .; then
  log "$NAME container exists (stopped) — restarting..."
  docker start "$NAME" >/dev/null 2>&1
  log "docker start exit: $?"
else
  log "No container — fresh start via paiton launcher"
  log "Running: bash /home/j/Desktop/AI/paiton-qwen38.sh start"
  bash /home/j/Desktop/AI/paiton-qwen38.sh start 2>&1 | tee -a "$LOG"
  log "paiton launcher exit: ${PIPESTATUS[0]}"
fi
# log follow for the manager's log viewer
pkill -f "docker logs -f $NAME" 2>/dev/null || true
nohup docker logs -f "$NAME" >> /home/j/logs/vllm_big.log 2>&1 &
log "$NAME starting (log: /home/j/logs/vllm_big.log)"
log "=== mgr_big_start.sh finished ==="
