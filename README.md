# Cozmo Dashboard

A self-contained app for controlling an Anki Cozmo robot directly over WiFi,
using [pycozmo](https://github.com/zayfod/pycozmo) instead of Anki's
(now-shut-down) cloud service. Built for a kid to run on a dedicated laptop:
drive Cozmo, play animations, make him talk, and see through his camera.

## Status

- **Stage 1** (project setup + connection test): done
- **Stage 2** (Flask backend: driving, head/lift, animations, TTS, camera):
  done, verified against real hardware
- **Stage 3** (kid-friendly frontend UI): done, verified in-browser against
  a simulated Cozmo connection; not yet tested against real hardware
- **Stage 4** (one-click kiosk launcher): done. Windows version verified
  end-to-end here (readiness detection, Chrome app-mode window, cleanup on
  close/timeout); Linux version written the same way but not yet run on
  the real Endless laptop

## How it's structured

- `backend/` -- the Flask app and everything that talks to Cozmo
  - `cozmo_service.py` -- the only file that calls `pycozmo` directly
  - `animations.py` -- curated, kid-friendly animation buttons (edit this
    to add/rename animations, no code changes needed elsewhere)
  - `tts.py` -- offline text-to-speech, normalized to the audio format
    Cozmo's speaker requires, plus a tunable "robot voice" effect
  - `app.py` -- the HTTP API (binds to `127.0.0.1` only)
  - `manual_test.py` -- standalone hardware test, no browser/frontend
    needed (see "Testing against real Cozmo" below)
- `frontend/` -- the browser UI: D-pad driving, head/lift, animation
  buttons (generated from `backend/animations.py`, not hardcoded here),
  a talk box, and a live camera view. `style.css` has the colors/sizes as
  CSS variables at the top if you want to reskin it. Also keyboard-
  controllable: arrow keys drive, numpad `2`/`0` tilt the head, numpad
  `3`/`.` move the lift, and either Ctrl key is an instant stop -- see
  `KEYBOARD_HOLD_KEYS` in `app.js` to remap.
- `connection_test.py` -- the original minimal Stage 1 connection check
- `launch_linux.sh` / `launch_windows.ps1` + `Play with Cozmo.bat` -- the
  one-click launchers (see "Playing with Cozmo" below)

## Setup

### Windows

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python .venv\Scripts\pycozmo_resources.py download
```

The last command does a one-time download (~a few hundred MB) of Cozmo's
animation/sound assets from a community GitHub mirror (Anki's own servers
are gone). Needs normal internet access; not needed again after this.

### Linux (Endless OS / Debian-based)

```bash
chmod +x setup_linux.sh
./setup_linux.sh
```

Endless OS's base system is **read-only** (it's built on OSTree, like Fedora
Silverblue) -- `apt`/`sudo` package installs don't work there. This script
deliberately never uses them: it only touches this project's own folder in
your home directory, which is writable. It creates the same venv as above,
downloads Cozmo's assets, downloads an offline speech voice for
[piper-tts](https://github.com/OHF-Voice/piper1-gpl) (used instead of
`pyttsx3` on Linux, since `pyttsx3`'s Linux backend needs a system-installed
`espeak` binary -- piper is a plain pip package with everything bundled
in), and adds two entries to the app grid (searchable the same way as
Terminal/Settings -- Endless OS doesn't show desktop icons): "Play with
Cozmo" (the actual app) and "Cozmo Hardware Test" (troubleshooting).

## Testing against real Cozmo

Both platforms use the same test: it connects, then drives, turns, moves
his head/lift, plays an animation, speaks a phrase, and saves a camera
snapshot -- while checking after every step that Cozmo is actually still
responding (see the note in `manual_test.py` about why that check matters:
commands to Cozmo are one-way UDP, so a dropped WiFi link does NOT raise an
error on its own).

1. Join this laptop's WiFi to Cozmo's own hotspot (shown on his screen when
   he's on). You'll lose normal internet access while connected to him.
2. Windows: double-click `Run Hardware Test.bat`.
   Linux: search the app grid for "Cozmo Hardware Test" and click it (or
   run `.venv/bin/python backend/manual_test.py`).
3. Watch Cozmo and read the terminal output -- it tells you plainly whether
   every step was confirmed or whether the WiFi link dropped partway
   through.

## Playing with Cozmo (the one-click launcher)

Join Cozmo's WiFi, then:
- Windows: double-click `Play with Cozmo.bat`.
- Linux: search the app grid for "Play with Cozmo" and click it.

This starts the backend, waits until it's actually connected to Cozmo,
then opens the dashboard in a Chromium "app" window -- fullscreen, no
tabs/address bar. Closing that window automatically stops the backend
too, so there's nothing left running in the background afterward (see
`launch_linux.sh` / `launch_windows.ps1` for exactly how). If Cozmo isn't
reachable, it says so plainly instead of leaving a blank/frozen window.

On Linux specifically, it picks whichever of `chromium-browser`,
`chromium`, `google-chrome-stable`, or `google-chrome` is actually
installed, rather than assuming one -- Endless OS ships Chromium by
default, but this doesn't hardcode that.

## Running the backend directly (no launcher, e.g. for development)

```
# Windows
.venv\Scripts\python backend\app.py

# Linux
.venv/bin/python backend/app.py
```

Serves on `http://127.0.0.1:5000` -- deliberately not reachable from other
devices, since this is meant to run and be used entirely on one laptop.
Stop it with Ctrl+C in that terminal (or `pkill -f backend/app.py` /
`Get-Process python | Stop-Process` if you've lost track of which window
it's running in).
