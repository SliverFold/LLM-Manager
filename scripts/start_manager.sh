#!/bin/bash

LOG_FILE="/root/logs/model_manager.log"
PID_FILE="/root/logs/model_manager.pid"

# Create the log directory
mkdir -p /root/logs

# Check if it is already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Manager already running (PID: $OLD_PID)"
        echo "URL: http://0.0.0.0:9000"
        exit 0
    fi
fi

# Check dependencies
echo "Checking Python dependencies..."
pip3 list | grep -q flask || pip3 install flask flask-cors psutil

# Start the service
echo "Starting the manager..."
cd /root/vllm-model-manager
nohup python3 app.py > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

echo "Service starting, log: $LOG_FILE"
echo "Waiting for the service to be ready..."

# Wait for the service to start
for i in {1..30}; do
    if curl -s http://localhost:9000 > /dev/null 2>&1; then
        echo "✓ Service ready!"
        echo "URL: http://0.0.0.0:9000"
        echo "View logs: tail -f $LOG_FILE"
        exit 0
    fi
    sleep 1
done

echo "Start timed out, check the log: tail -f $LOG_FILE"
exit 1
