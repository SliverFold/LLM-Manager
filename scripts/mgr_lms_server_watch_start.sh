#!/bin/bash
# mgr_lms_server_watch_start.sh — start the LM Studio server watcher
# (ties the LM Studio headless server lifecycle to the model lifecycle:
#  model loaded -> server starts; model unloaded -> server stops)
# Uses a PID file so the stop script can kill the exact process (no pattern
# matching, which would match the Hermes terminal wrapper).

WATCH_SCRIPT="/home/j/.lmstudio/bin/lms-server-watch.sh"
LOG_FILE="/home/j/logs/lms_server_watch.log"
PID_FILE="/home/j/.lmstudio/bin/lms-server-watch.pid"

# Already running? (check the PID file)
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "lms-server-watch already running (pid $(cat "$PID_FILE"))"
    exit 0
fi

# Start the watcher in the background and record its PID
nohup "$WATCH_SCRIPT" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "lms-server-watch started (pid $(cat "$PID_FILE"))"
