#!/usr/bin/env bash
#
# Start Pulpit: activate the virtual environment, launch the Django development
# server, and open the home page in your default browser.
#
# Usage: ./run.sh [PORT]
#   PORT defaults to 8000. Override with an argument (./run.sh 9000) or the
#   PULPIT_PORT environment variable.

set -e

# Move to the project root (the directory containing this script) so the script
# works no matter where it is invoked from.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="127.0.0.1"
PORT="${1:-${PULPIT_PORT:-8000}}"
URL="http://${HOST}:${PORT}/"

# Make sure the virtual environment exists before doing anything else.
if [ ! -f ".venv/bin/activate" ]; then
    echo "Error: virtual environment not found (.venv)." >&2
    echo "Run ./setup.sh first to create it." >&2
    exit 1
fi

# Activate the virtual environment.
# shellcheck disable=SC1091
source ".venv/bin/activate"

# Open a URL using whatever the platform provides.
open_url() {
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$1" >/dev/null 2>&1 &     # most Linux desktops
    elif command -v open >/dev/null 2>&1; then
        open "$1"                           # macOS
    elif command -v wslview >/dev/null 2>&1; then
        wslview "$1"                        # Windows Subsystem for Linux
    else
        echo "Open $1 in your browser."
    fi
}

# Wait until the server answers (capped at ~30s), then open the browser.
wait_then_open() {
    i=0
    while [ "$i" -lt 60 ]; do
        if command -v curl >/dev/null 2>&1; then
            if curl -sS -o /dev/null "$URL" 2>/dev/null; then break; fi
        elif command -v wget >/dev/null 2>&1; then
            if wget -q -O /dev/null "$URL" 2>/dev/null; then break; fi
        else
            sleep 2
            break
        fi
        i=$((i + 1))
        sleep 0.5
    done
    open_url "$URL"
}

echo "Starting Pulpit at ${URL}"
echo "The browser will open automatically once the server is ready."
echo "Press Ctrl+C to stop the server."

# Open the browser in the background once the server is up, then run the server
# in the foreground so Ctrl+C stops it cleanly.
wait_then_open &
OPENER_PID=$!
trap 'kill "$OPENER_PID" 2>/dev/null || true' EXIT

python manage.py runserver "${HOST}:${PORT}"
