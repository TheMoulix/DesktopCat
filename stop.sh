#!/usr/bin/env bash
# DesktopCat - Stop running instance
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOCK_FILE="$SCRIPT_DIR/.cat_instance.lock"
STOPPED=0

if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill -15 "$PID" 2>/dev/null || true
        echo "🐱 DesktopCat (PID $PID) stopped."
        rm -f "$LOCK_FILE"
        STOPPED=1
    fi
fi

# Fallback in case PID file was stale or process didn't close
if pkill -f "cat_overlay.*" 2>/dev/null; then
    echo "🐱 DesktopCat process terminated."
    STOPPED=1
fi

rm -f "$LOCK_FILE"

if [ $STOPPED -eq 0 ]; then
    echo "DesktopCat was not running."
fi
