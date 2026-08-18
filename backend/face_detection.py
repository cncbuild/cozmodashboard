"""
Face detection on Cozmo's camera feed.

This is genuinely new functionality, not a restoration of anything Cozmo
used to do -- the original app's face recognition ran on the connected
phone (via Anki's own proprietary engine processing the video Cozmo
streamed to it), not on the robot, and pycozmo doesn't implement any of
that protocol. This builds basic face *detection* ourselves, from
scratch, using Cozmo's live camera feed we already have. Recognizing and
naming specific people is a deliberately separate, later step -- this
only answers "is a face there right now", not "whose".

Uses OpenCV's classic Haar cascade detector (`cv2.CascadeClassifier`) --
not the most accurate face detector available, but fast, needs no GPU,
and has been solid for two decades, which matters more here than raw
accuracy on a laptop that might be old/underpowered.

The cascade model file (models/haarcascade_frontalface_default.xml) is
downloaded from OpenCV's own repository and committed directly into this
project, rather than relying on it being bundled with the opencv-python
package -- that bundling has changed between OpenCV versions (as of
OpenCV 5.0, the classifier data isn't bundled at all anymore), so keeping
our own copy means this doesn't break if that changes again.
"""

import pathlib

import cv2
import numpy as np
from PIL import Image, ImageDraw

CASCADE_PATH = pathlib.Path(__file__).parent / "models" / "haarcascade_frontalface_default.xml"

# Tuning knobs for detectMultiScale -- see OpenCV's docs if you want to
# adjust sensitivity. Roughly: lower minNeighbors = more detections but
# more false positives; larger minSize = ignores small/distant faces.
SCALE_FACTOR = 1.1
MIN_NEIGHBORS = 5
MIN_FACE_SIZE = (40, 40)

# Color and thickness of the box drawn around detected faces.
BOX_COLOR = (255, 210, 0)
BOX_WIDTH = 4

# Steady-state detection is fast regardless of image size (~10-15ms in
# testing, whether 320x320 or 512x512) -- but a bigger image still means
# more work in the RGB->grayscale conversion and Haar feature scanning
# before that steady state, and Cozmo's camera resolution/the deployment
# laptop's CPU are both unknowns. Downscaling to this on the longest side
# before detection (boxes get scaled back up afterward) keeps things fast
# and predictable without depending on those unknowns.
MAX_DETECTION_SIZE = 320

_cascade = None


def _get_cascade() -> cv2.CascadeClassifier:
    global _cascade
    if _cascade is None:
        if not CASCADE_PATH.exists():
            raise RuntimeError(f"Face cascade file not found at {CASCADE_PATH}")
        _cascade = cv2.CascadeClassifier(str(CASCADE_PATH))
        if _cascade.empty():
            raise RuntimeError(f"Failed to load face cascade from {CASCADE_PATH}")
    return _cascade


def warm_up() -> None:
    """
    Loads the cascade and runs one throwaway detection. In testing,
    detectMultiScale's FIRST call ever (regardless of image size) costs
    about half a second -- likely internal one-time setup -- while every
    call after that takes ~10-15ms. Call this once during startup so that
    cost happens before the camera starts streaming, not as a delay on
    the first real frame Cozmo sends.
    """
    cascade = _get_cascade()
    cascade.detectMultiScale(np.zeros((100, 100), dtype=np.uint8))


def detect_faces(image: Image.Image) -> list:
    """
    Returns a list of (x, y, w, h) pixel bounding boxes -- in the
    ORIGINAL image's coordinates -- for every face found in a PIL image.
    Empty list if none found.
    """
    cascade = _get_cascade()

    # Downscale before detection if needed (see MAX_DETECTION_SIZE), then
    # scale the resulting boxes back up so they still line up correctly
    # on the original, full-size image.
    width, height = image.size
    longest_side = max(width, height)
    scale = 1.0
    detection_image = image
    if longest_side > MAX_DETECTION_SIZE:
        scale = longest_side / MAX_DETECTION_SIZE
        detection_image = image.resize(
            (max(1, int(width / scale)), max(1, int(height / scale)))
        )

    gray = cv2.cvtColor(np.array(detection_image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    boxes = cascade.detectMultiScale(
        gray,
        scaleFactor=SCALE_FACTOR,
        minNeighbors=MIN_NEIGHBORS,
        minSize=MIN_FACE_SIZE,
    )
    return [tuple(int(v * scale) for v in box) for box in boxes]


def draw_face_boxes(image: Image.Image, boxes: list) -> Image.Image:
    """Returns a COPY of `image` with a rectangle drawn around each face box."""
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for (x, y, w, h) in boxes:
        draw.rectangle([x, y, x + w, y + h], outline=BOX_COLOR, width=BOX_WIDTH)
    return annotated
