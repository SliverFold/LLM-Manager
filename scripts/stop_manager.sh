#!/bin/bash

PID_FILE="/root/logs/model_manager.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping the manager (PID: $PID)..."
        kill "$PID"
        sleep 2
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Force killing..."
            kill -9 "$PID"
        fi
        rm -f "$PID_FILE"
        echo "Service stopped"
    else
        echo "Service not running"
        rm -f "$PID_FILE"
    fi
else
    # Try to find it by process name
    if pgrep -f "python3 app.py" > /dev/null; then
        echo "Stopping the manager..."
        pkill -f "python3 app.py"
        sleep 2
        if pgrep -f "python3 app.py" > /dev/null; then
            echo "Force killing..."
            pkill -9 -f "python3 app.py"
        fi
        echo "Service stopped"
    else
        echo "Service not running"
    fi
fi
