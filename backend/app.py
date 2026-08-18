"""
Flask backend for the Cozmo dashboard.

Run this directly to start the server:

    "D:\\Projects\\Cozmo Dashboard\\.venv\\Scripts\\python.exe" backend\\app.py

It connects to Cozmo first (so by the time the server is actually accepting
requests, Cozmo is ready to go), then serves both the JSON API the frontend
uses and the frontend's static files themselves.

Binds to 127.0.0.1 only -- nothing outside this laptop can reach it, which
is deliberate: this app is meant to be opened in a kiosk browser on the same
machine, not accessed remotely.
"""

import logging
import sys
import threading

from flask import Flask, Response, jsonify, request, send_from_directory

import pycozmo
from animations import ANIMATIONS
from cozmo_service import MAX_WHEEL_SPEED, service
from known_faces import known_faces

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("app")

# Flask's dev server logs every single request at INFO level by default --
# the dashboard alone generates one every ~2s just from its own status
# polling, which drowns out genuinely useful log lines (like "Connected to
# Cozmo") in a hurry. Quiet it down to warnings/errors only.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# Full wheel speed (pycozmo.MAX_WHEEL_SPEED) is quite fast for indoor,
# kid-supervised driving. The D-pad/joystick in the frontend sends values
# from -1..1; this scales that down to a friendlier top speed. Turn this up
# toward 1.0 once you're comfortable with how fast that actually is.
DRIVE_SPEED_SCALE = 0.6

FRONTEND_DIR = "../frontend"

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")


def _json_body() -> dict:
    return request.get_json(force=True, silent=True) or {}


def _require_connected():
    """
    Guards every action route. Checking `service.connected` alone isn't
    enough -- pycozmo sends commands as fire-and-forget UDP, so if Cozmo's
    WiFi link has silently dropped, `connected` stays True forever even
    though nothing is actually reaching him. `is_alive()` catches that by
    requiring a recent real response from Cozmo, not just an open socket.
    """
    if not service.connected:
        return jsonify(error="Not connected to Cozmo."), 503
    if not service.is_alive():
        gap = round(service.seconds_since_last_response(), 1)
        return jsonify(error=f"Cozmo hasn't responded in {gap}s -- WiFi link may have dropped."), 503
    return None


# ----------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ----------------------------------------------------------------------
# Status
# ----------------------------------------------------------------------

@app.route("/api/status")
def status():
    """
    `connected` means the backend has a Cozmo client object at all.
    `alive` means Cozmo has actually sent us something recently -- this is
    the one that catches "WiFi dropped mid-session", which `connected`
    alone will NOT catch (see the comment on CozmoService.is_alive).
    """
    return jsonify(
        connected=service.connected,
        alive=service.is_alive() if service.connected else False,
        seconds_since_last_response=(
            round(service.seconds_since_last_response(), 1) if service.connected else None
        ),
    )


# ----------------------------------------------------------------------
# Driving
# ----------------------------------------------------------------------

@app.route("/api/drive", methods=["POST"])
def drive():
    """
    Body: {"left": -1..1, "right": -1..1}
    Call repeatedly (e.g. every ~150ms) while a drive button/joystick is
    held. If calls stop arriving, the backend's watchdog stops Cozmo
    automatically -- see COMMAND_TIMEOUT in cozmo_service.py.
    """
    if (err := _require_connected()) is not None:
        return err
    body = _json_body()
    try:
        left = float(body.get("left", 0))
        right = float(body.get("right", 0))
    except (TypeError, ValueError):
        return jsonify(error="left/right must be numbers"), 400
    service.drive(left * MAX_WHEEL_SPEED * DRIVE_SPEED_SCALE,
                  right * MAX_WHEEL_SPEED * DRIVE_SPEED_SCALE)
    return jsonify(ok=True)


@app.route("/api/drive/stop", methods=["POST"])
def drive_stop():
    if (err := _require_connected()) is not None:
        return err
    service.stop_drive()
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Head
# ----------------------------------------------------------------------

@app.route("/api/head", methods=["POST"])
def head_move():
    """Body: {"speed": -1..1}. Continuous, held-button style like /api/drive."""
    if (err := _require_connected()) is not None:
        return err
    body = _json_body()
    try:
        speed = float(body.get("speed", 0))
    except (TypeError, ValueError):
        return jsonify(error="speed must be a number"), 400
    service.move_head(speed)
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Lift
# ----------------------------------------------------------------------

@app.route("/api/lift", methods=["POST"])
def lift_move():
    """Body: {"speed": -1..1}. Continuous, held-button style like /api/drive."""
    if (err := _require_connected()) is not None:
        return err
    body = _json_body()
    try:
        speed = float(body.get("speed", 0))
    except (TypeError, ValueError):
        return jsonify(error="speed must be a number"), 400
    service.move_lift(speed)
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Animations
# ----------------------------------------------------------------------

@app.route("/api/animations")
def list_animations():
    """Returns the curated animation list from animations.py, for the
    frontend to render buttons from -- add/edit animations there, not here
    or in the frontend."""
    return jsonify(ANIMATIONS)


@app.route("/api/animations/<key>", methods=["POST"])
def play_animation(key: str):
    if (err := _require_connected()) is not None:
        return err
    try:
        service.play_animation(key)
    except ValueError as e:
        return jsonify(error=str(e)), 404
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Text-to-speech
# ----------------------------------------------------------------------

@app.route("/api/say", methods=["POST"])
def say():
    """Body: {"text": "..."}. Speech synthesis + playback take a few
    seconds, so this runs in a background thread and returns immediately
    rather than making the browser wait for Cozmo to finish talking."""
    if (err := _require_connected()) is not None:
        return err
    body = _json_body()
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify(error="text must not be empty"), 400
    if len(text) > 500:
        return jsonify(error="text is too long (max 500 characters)"), 400

    def _speak():
        try:
            service.say(text)
        except Exception:
            logger.exception("Error while Cozmo was speaking")

    threading.Thread(target=_speak, daemon=True).start()
    return jsonify(ok=True)


# ----------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------

@app.route("/api/camera/frame")
def camera_frame():
    """A single current JPEG snapshot -- handy for testing."""
    if (err := _require_connected()) is not None:
        return err
    jpeg = service.get_latest_jpeg(timeout=2.0)
    if jpeg is None:
        return jsonify(error="No camera frame received yet."), 503
    return Response(jpeg, mimetype="image/jpeg")


@app.route("/api/camera/stream")
def camera_stream():
    """Live MJPEG stream -- point an <img> tag's src at this URL."""
    if (err := _require_connected()) is not None:
        return err

    def _generate():
        while True:
            jpeg = service.get_latest_jpeg(timeout=5.0)
            if jpeg is None:
                continue
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")

    return Response(_generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ----------------------------------------------------------------------
# Face detection & recognition
# ----------------------------------------------------------------------

@app.route("/api/face-detection")
def face_detection_status():
    """
    Detected face boxes (and name labels, for recognized faces) are
    already drawn directly onto the camera stream above (see
    CozmoService._on_camera_image), so this is only for a small text
    status the frontend can show without staring at the video -- not
    gated behind _require_connected() since it's read-only status, not
    an action: just reports zero faces if not connected.

    `names` is the same length as face_count -- an entry is a name if
    that face matched someone enrolled, or null if it didn't.
    """
    if not service.connected:
        return jsonify(face_detected=False, face_count=0, names=[])
    count = service.get_face_count()
    return jsonify(face_detected=count > 0, face_count=count, names=service.get_face_names())


@app.route("/api/faces")
def list_known_faces():
    """Names of everyone currently enrolled."""
    return jsonify(names=known_faces.names())


@app.route("/api/faces/enroll", methods=["POST"])
def enroll_face():
    """
    Body: {"name": "..."}. Enrolls whoever is currently in frame under
    that name -- fails with a kid-readable error if there's nobody (or
    more than one person) visible right now.
    """
    if (err := _require_connected()) is not None:
        return err
    body = _json_body()
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="Please type a name first."), 400
    if len(name) > 50:
        return jsonify(error="That name is too long."), 400
    error = service.enroll_face(name)
    if error:
        return jsonify(error=error), 400
    return jsonify(ok=True)


@app.route("/api/faces/<name>", methods=["DELETE"])
def forget_face(name: str):
    if known_faces.forget(name):
        return jsonify(ok=True)
    return jsonify(error=f"{name!r} isn't a known face."), 404


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def main() -> None:
    print("Connecting to Cozmo...")
    print("(Make sure this laptop's WiFi is joined to Cozmo's hotspot first.)")
    try:
        service.connect()
    except pycozmo.exception.PyCozmoException as e:
        print(f"\nCozmo connection error: {e}")
        print("Double check this laptop's WiFi is connected to Cozmo's hotspot,")
        print("and that Cozmo is awake (not asleep/on charger with screen off).")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)

    print("Connected! Starting server on http://127.0.0.1:5000 ...")
    try:
        # threaded=True so a slow request (e.g. /api/say, which takes a few
        # seconds) doesn't block driving/camera requests from being handled.
        app.run(host="127.0.0.1", port=5000, threaded=True)
    finally:
        service.disconnect()


if __name__ == "__main__":
    main()
