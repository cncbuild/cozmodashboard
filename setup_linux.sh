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
if .venv/bin/pycozmo_resources.py status >/dev/null 2>&1; then
    echo "Already downloaded, skipping."
else
    .venv/bin/pycozmo_resources.py download
fi

echo "== Downloading the offline text-to-speech voice (one-time, ~60MB) =="
mkdir -p voices
if [ -f "voices/en_US-lessac-medium.onnx" ]; then
    echo "Already downloaded, skipping."
else
    .venv/bin/python -m piper.download_voices en_US-lessac-medium --download-dir voices
fi

echo "== Creating a double-click desktop icon for the hardware test =="
DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"
LAUNCHER="$DESKTOP_DIR/Cozmo Hardware Test.desktop"
cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Cozmo Hardware Test
Comment=Run the Stage 2 backend hardware test against a real Cozmo
Exec=bash -c 'cd "$PROJECT_DIR" && .venv/bin/python backend/manual_test.py; echo; read -p "Test finished. Press Enter to close..."'
Icon=utilities-terminal
Terminal=true
EOF
chmod +x "$LAUNCHER"

echo ""
echo "Setup complete!"
echo ""
echo "A 'Cozmo Hardware Test' icon was added to your Desktop. The first"
echo "time you double-click it, the desktop environment may refuse to run"
echo "it until you right-click it and choose 'Allow Launching' (a one-time"
echo "security confirmation for new desktop icons) -- after that, it just"
echo "double-clicks and runs normally."
echo ""
echo "To use it: join this laptop's WiFi to Cozmo's hotspot, then"
echo "double-click the 'Cozmo Hardware Test' icon on your Desktop."
