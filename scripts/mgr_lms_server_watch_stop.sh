#!/bin/bash
# mgr_lms_server_watch_stop.sh — stop the LM Studio server watcher
# (uses the PID file to kill the exact process, no pattern matching)

PID_FILE="/home/j/.lmstudio/bin/lms-server-watch.pid"

# Kill the watcher process (using the PID file)
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID=$(cat "$PID_FILE")
    kill "$PID"
    rm -f "$PID_FILE"
    echo "lms-server-watch stopped (pid $PID)"
else
    rm -f "$PID_FILE"
    echo "lms-server-watch not running"
fi
