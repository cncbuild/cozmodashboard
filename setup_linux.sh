#!/usr/bin/env bash
#
# One-time setup for running the Cozmo dashboard on Linux -- written for
# Endless OS, whose base system is READ-ONLY (it's built on OSTree, similar
# to Fedora Silverblue), so this deliberately does NOT use apt/sudo for
# anything -- system-level installs simply don't work there. Everything
# below only touches this project's own folder and the venv inside it,
# both in the user's own writable home directory, matching the approach
# Endless's own community documents for getting Python working there.
# Should also work unchanged on regular Ubuntu/Debian/Mint.
#
# Run this ONCE, right after cloning the repo, while this laptop still has
# normal internet access. It installs Python packages and downloads Cozmo's
# animation/sound assets plus a speech voice model, none of which will be
# reachable later once this laptop switches its WiFi to Cozmo's own hotspot.
#
# Usage:
#   chmod +x setup_linux.sh
#   ./setup_linux.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "== Creating Python virtual environment (.venv) =="
python3 -m venv .venv

echo "== Installing Python packages =="
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "== Downloading Cozmo's animation/sound assets (one-time, a few hundred MB) =="
# Invoked as ".venv/bin/python <script>" rather than running the script
# directly -- pycozmo installs this as an old-style "raw script", and its
# auto-generated first line (which names the exact Python interpreter to
# use) breaks if the path to this project folder contains a space, like
# "Cozmo Dashboard" does. Explicitly naming the interpreter here sidesteps
# that entirely.
if .venv/bin/python .venv/bin/pycozmo_resources.py status >/dev/null 2>&1; then
    echo "Already downloaded, skipping."
else
    .venv/bin/python .venv/bin/pycozmo_resources.py download
fi

echo "== Downloading the offline text-to-speech voice (one-time, ~60MB) =="
mkdir -p voices
if [ -f "voices/en_US-lessac-medium.onnx" ]; then
    echo "Already downloaded, skipping."
else
    .venv/bin/python -m piper.download_voices en_US-lessac-medium --download-dir voices
fi

echo "== Adding 'Cozmo Hardware Test' to the app grid =="
# Endless OS's shell is an app-grid launcher (like the one you used to find
# Terminal/Settings), not a classic desktop with icons -- files placed in
# ~/Desktop generally aren't shown there at all. ~/.local/share/applications
# is the standard place any Linux desktop looks for user-installed apps, so
# this makes the test searchable/clickable the same way Terminal already is.
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
LAUNCHER="$APPS_DIR/cozmo-hardware-test.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Cozmo Hardware Test
Comment=Run the Stage 2 backend hardware test against a real Cozmo
Exec=bash -c 'cd "$PROJECT_DIR" && .venv/bin/python backend/manual_test.py; echo; read -p "Test finished. Press Enter to close..."'
Icon=utilities-terminal
Terminal=true
Categories=Utility;
EOF
chmod +x "$LAUNCHER"

echo ""
echo "Setup complete!"
echo ""
echo "To use it: join this laptop's WiFi to Cozmo's hotspot, then open the"
echo "app grid and search for 'Cozmo Hardware Test' (same way you found"
echo "Terminal/Settings earlier), and click it."
