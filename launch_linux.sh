#!/usr/bin/env bash
#
# The "one click to play" launcher for Linux/Endless OS. Starts the
# backend, waits until it's actually ready (it doesn't finish starting
# until it's connected to Cozmo), opens the dashboard in a browser "app"
# window -- fullscreen, no tabs/address bar, so it doesn't look like a
# normal browser -- and stops the backend automatically when that window
# is closed.
#
# setup_linux.sh creates an app-grid entry that runs this, so you
# shouldn't normally need to run it by hand -- but it works fine directly:
#   ./launch_linux.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Start the backend in the background.
.venv/bin/python backend/app.py &
BACKEND_PID=$!

# Whatever happens below, make sure the backend doesn't keep running after
# this script exits (e.g. after the browser window is closed).
cleanup() {
    kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Wait until the backend is actually answering -- it blocks on connecting
# to Cozmo before it starts serving, which can take a few seconds. Uses
# our own venv's Python rather than curl/wget so this doesn't depend on
# anything beyond what setup_linux.sh already installed.
echo "Starting up..."
READY=0
for _ in $(seq 1 60); do
    if .venv/bin/python -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://127.0.0.1:5000/api/status', timeout=1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        READY=1
        break
    fi
    # If the backend process already died (e.g. Cozmo unreachable), stop
    # waiting instead of burning the full 60 seconds.
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

if [ "$READY" -ne 1 ]; then
    echo ""
    echo "Cozmo isn't responding -- make sure this laptop's WiFi is joined"
    echo "to his hotspot and he's turned on, then try again."
    read -p "Press Enter to close..."
    exit 1
fi

# Find whichever Chromium-family browser is actually installed, in order
# of preference, rather than hardcoding one exact binary name (Endless OS
# ships Chromium by default, but this works unchanged if that ever
# changes, or on a different Linux distro).
BROWSER=""
for candidate in chromium-browser chromium google-chrome-stable google-chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
        BROWSER="$candidate"
        break
    fi
done

if [ -z "$BROWSER" ]; then
    echo "No Chromium-based browser found -- opening with the system default"
    echo "browser instead (it'll show tabs/address bar, unlike --kiosk mode)."
    xdg-open http://127.0.0.1:5000
    wait "$BACKEND_PID"
else
    # --kiosk on its own removes tabs/address bar/toolbars AND goes
    # fullscreen. Deliberately NOT combined with --app -- Chromium's --app
    # and --kiosk flags conflict with each other, and the combination
    # often falls back to a plain windowed browser instead of true
    # fullscreen (confirmed on this project's real Endless OS laptop).
    # --noerrdialogs/--disable-infobars hide the "restore pages?" and
    # similar popups a kid shouldn't have to deal with. This call blocks
    # until the window is closed, at which point the `trap cleanup EXIT`
    # above stops the backend too.
    "$BROWSER" \
        --kiosk http://127.0.0.1:5000 \
        --noerrdialogs \
        --disable-infobars \
        --disable-session-crashed-bubble
fi
