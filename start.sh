#!/usr/bin/env bash
# DesktopCat - Launcher for Linux
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if already running
if [ -f "$SCRIPT_DIR/.cat_instance.lock" ]; then
    PID=$(cat "$SCRIPT_DIR/.cat_instance.lock" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "🐱 DesktopCat is already running (PID $PID)."
        exit 0
    fi
fi

nohup python3 "$SCRIPT_DIR/cat_overlay.py" </dev/null &>/dev/null &
echo "🐱 DesktopCat started in background."
