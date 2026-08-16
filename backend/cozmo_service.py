"""
Owns the single persistent connection to Cozmo.

Flask routes (in app.py) should only ever call methods on the shared
`service` object defined at the bottom of this file -- they should never
import `pycozmo` directly. That keeps every "how do I actually talk to
Cozmo" detail in one place, so if pycozmo's API ever changes, this is the
only file that needs updating.
"""

import io
import logging
import threading
import time
from typing import Optional

import pycozmo

from animations import ANIMATIONS
from tts import synthesize_speech_wav

logger = logging.getLogger("cozmo_service")

# How long (seconds) a driving/head/lift command stays valid without a
# follow-up "still holding the button" message from the browser before we
# treat it as released and stop the motor ourselves. This is a safety net:
# if a browser tab freezes, misses a mouseup/touchend event, or the local
# request hiccups, Cozmo won't keep driving/moving forever.
COMMAND_TIMEOUT = 0.5

# How often the watchdog thread checks for stale commands.
WATCHDOG_INTERVAL = 0.15

# Cozmo's real hardware limits, re-exported as plain numbers so the rest of
# the app doesn't need to import pycozmo just to clamp a value.
MAX_WHEEL_SPEED = pycozmo.MAX_WHEEL_SPEED.mmps
MIN_HEAD_ANGLE = pycozmo.MIN_HEAD_ANGLE.radians
MAX_HEAD_ANGLE = pycozmo.MAX_HEAD_ANGLE.radians
MIN_LIFT_HEIGHT = pycozmo.MIN_LIFT_HEIGHT.mm
MAX_LIFT_HEIGHT = pycozmo.MAX_LIFT_HEIGHT.mm


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class CozmoService:
    """Wraps a single persistent pycozmo.Client connection to Cozmo."""

    def __init__(self) -> None:
        self._client: Optional[pycozmo.Client] = None

        # Timestamps of the last "held button" command of each kind,
        # used by the watchdog thread to auto-stop stale motion.
        self._last_drive_cmd = 0.0
        self._last_head_cmd = 0.0
        self._last_lift_cmd = 0.0
        self._driving = False
        self._moving_head = False
        self._moving_lift = False

        # Most recent camera frame, pre-encoded as JPEG bytes, plus a
        # condition variable so the camera streaming endpoint can wait
        # efficiently for the next frame instead of busy-polling.
        self._latest_jpeg: Optional[bytes] = None
        self._frame_condition = threading.Condition()

        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_watchdog = threading.Event()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to Cozmo and block until he confirms he's alive."""
        logger.info("Connecting to Cozmo...")
        client = pycozmo.Client()
        client.start()
        client.connect()
        client.wait_for_robot()
        self._client = client

        # Turn on the camera and register a handler that keeps only the
        # single most recent frame -- we don't need a history, just
        # "what does Cozmo see right now".
        client.enable_camera(enable=True, color=True)
        client.add_handler(pycozmo.EvtNewRawCameraImage, self._on_camera_image)

        self._stop_watchdog.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

        logger.info("Connected to Cozmo.")

    def disconnect(self) -> None:
        self._stop_watchdog.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)
        if self._client:
            self._client.disconnect()
            self._client.stop()
            self._client = None

    @property
    def client(self) -> pycozmo.Client:
        if self._client is None:
            raise RuntimeError("Not connected to Cozmo yet.")
        return self._client

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # Driving
    # ------------------------------------------------------------------

    def drive(self, left: float, right: float) -> None:
        """
        Set both wheel speeds directly, in mm/s (positive = forward).
        Call this repeatedly (e.g. every ~150ms) for as long as a drive
        button/joystick is held -- if these calls stop arriving, the
        watchdog stops the motors automatically, so a missed "release"
        event can't leave Cozmo driving forever.
        """
        left = _clamp(left, -MAX_WHEEL_SPEED, MAX_WHEEL_SPEED)
        right = _clamp(right, -MAX_WHEEL_SPEED, MAX_WHEEL_SPEED)
        self.client.drive_wheels(lwheel_speed=left, rwheel_speed=right)
        self._last_drive_cmd = time.monotonic()
        self._driving = left != 0 or right != 0

    def stop_drive(self) -> None:
        self.client.drive_wheels(lwheel_speed=0, rwheel_speed=0)
        self._driving = False

    # ------------------------------------------------------------------
    # Head / lift
    # ------------------------------------------------------------------

    def move_head(self, speed: float) -> None:
        """Continuous head movement. Speed in radians/sec, -1..1 is sensible."""
        self.client.move_head(speed)
        self._last_head_cmd = time.monotonic()
        self._moving_head = speed != 0

    def set_head_angle(self, angle: float, duration: float = 0.5) -> None:
        """One-shot move to an absolute head angle, in radians."""
        angle = _clamp(angle, MIN_HEAD_ANGLE, MAX_HEAD_ANGLE)
        self.client.set_head_angle(angle=angle, duration=duration)

    def move_lift(self, speed: float) -> None:
        """Continuous lift movement. Speed in radians/sec, -1..1 is sensible."""
        self.client.move_lift(speed)
        self._last_lift_cmd = time.monotonic()
        self._moving_lift = speed != 0

    def set_lift_height(self, height: float, duration: float = 0.5) -> None:
        """One-shot move to an absolute lift height, in millimeters."""
        height = _clamp(height, MIN_LIFT_HEIGHT, MAX_LIFT_HEIGHT)
        self.client.set_lift_height(height=height, duration=duration)

    # ------------------------------------------------------------------
    # Animations
    # ------------------------------------------------------------------

    def play_animation(self, key: str) -> None:
        """
        `key` is a friendly key from animations.ANIMATIONS (e.g. "happy"),
        not a raw pycozmo clip name -- edit animations.py to add/rename ones.
        """
        if key not in ANIMATIONS:
            raise ValueError(f"Unknown animation key: {key!r}")
        clip_name = ANIMATIONS[key]["clip"]
        self.client.play_anim(clip_name)

    # ------------------------------------------------------------------
    # Text-to-speech
    # ------------------------------------------------------------------

    def say(self, text: str) -> None:
        """
        Synthesizes `text` locally (no cloud) and plays it through Cozmo's
        speaker. Blocks until playback finishes -- call from a background
        thread (see app.py's /api/say route) if that's not desired.
        """
        wav_path = synthesize_speech_wav(text)
        try:
            self.client.play_audio(str(wav_path))
        finally:
            wav_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _on_camera_image(self, cli, image) -> None:
        del cli
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=70)
        with self._frame_condition:
            self._latest_jpeg = buf.getvalue()
            self._frame_condition.notify_all()

    def get_latest_jpeg(self, timeout: float = 1.0) -> Optional[bytes]:
        """Waits for the next camera frame (or returns the current one)."""
        with self._frame_condition:
            self._frame_condition.wait(timeout=timeout)
            return self._latest_jpeg

    # ------------------------------------------------------------------
    # Safety watchdog -- auto-stops motors if "held button" commands go stale
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._stop_watchdog.is_set():
            now = time.monotonic()
            if self._driving and now - self._last_drive_cmd > COMMAND_TIMEOUT:
                logger.debug("Drive watchdog: command went stale, stopping wheels.")
                self.stop_drive()
            if self._moving_head and now - self._last_head_cmd > COMMAND_TIMEOUT:
                self.client.move_head(0)
                self._moving_head = False
            if self._moving_lift and now - self._last_lift_cmd > COMMAND_TIMEOUT:
                self.client.move_lift(0)
                self._moving_lift = False
            time.sleep(WATCHDOG_INTERVAL)


# Single shared instance used by every Flask route in app.py.
service = CozmoService()
