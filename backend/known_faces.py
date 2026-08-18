"""
Recognizing and naming specific people Cozmo has met before.

Builds on face_detection.py (which only answers "is a face there") to
also answer "whose". Uses OpenCV's SFace model to turn a face crop into
a 512-number "feature" vector, then compares that against every enrolled
person's stored vector with cosine similarity -- the same idea as
face_detection.py's cascade file, the model is committed directly into
this project (models/face_recognition_sface.onnx) rather than relying on
opencv-python to bundle it.

Not using SFace's landmark-based alignCrop step, which is how it's
"properly" meant to be used -- that needs a landmark-aware detector
(e.g. FaceDetectorYN) instead of the simpler Haar cascade
face_detection.py deliberately uses. Tested the simpler crop-and-resize
approach directly instead: cosine similarity for the same person, under
real lighting/rotation changes, still came out around 0.85 against the
~0.36 "same person" threshold below -- solidly good enough for a home
use case, without needing a second downloaded model just for alignment.

PRIVACY NOTE: known_faces.json stores these feature vectors under
whatever name they're enrolled with. It's a form of biometric data (no
actual photos are stored, just numbers derived from a face) -- keep it
out of git (already in .gitignore). This matters more than it might for
a typical local file, since this project's repo is public.
"""

import json
import pathlib
import threading
from typing import Optional

import cv2
import numpy as np
from PIL import Image

MODEL_PATH = pathlib.Path(__file__).parent / "models" / "face_recognition_sface.onnx"
STORAGE_PATH = pathlib.Path(__file__).parent / "known_faces.json"

# SFace's own documented threshold for "same person" using cosine
# similarity (see https://github.com/opencv/opencv_zoo). Above this
# counts as a match; below it, the faces are considered different people.
MATCH_THRESHOLD = 0.363

FACE_CROP_SIZE = (112, 112)  # what SFace's model expects as input

_recognizer = None


def _get_recognizer() -> cv2.FaceRecognizerSF:
    global _recognizer
    if _recognizer is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(f"Face recognition model not found at {MODEL_PATH}")
        _recognizer = cv2.FaceRecognizerSF_create(str(MODEL_PATH), "")
    return _recognizer


def warm_up() -> None:
    """Same idea as face_detection.warm_up() -- pay any one-time cost
    now, during startup, rather than as a delay on first use."""
    recognizer = _get_recognizer()
    blank = np.zeros((*FACE_CROP_SIZE, 3), dtype=np.uint8)
    recognizer.feature(blank)


def _extract_feature(image: Image.Image, box) -> np.ndarray:
    """Crops `box` out of `image`, resizes it to what SFace expects, and
    returns its 512-number feature vector."""
    recognizer = _get_recognizer()
    x, y, w, h = box
    crop = image.crop((x, y, x + w, y + h)).resize(FACE_CROP_SIZE)
    arr = cv2.cvtColor(np.array(crop.convert("RGB")), cv2.COLOR_RGB2BGR)
    return recognizer.feature(arr)


class KnownFaces:
    """Holds enrolled people's face features in memory, persisted to
    STORAGE_PATH as plain JSON (feature vectors are just lists of
    numbers -- no photos stored). Accessed from both the camera thread
    (recognize, on every detected face) and Flask request threads
    (enroll/forget/names), hence the lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._people: dict = {}  # name -> list of feature vectors (np.ndarray)
        self._load()

    def _load(self) -> None:
        if not STORAGE_PATH.exists():
            return
        data = json.loads(STORAGE_PATH.read_text())
        self._people = {
            name: [np.array(f, dtype=np.float32) for f in features]
            for name, features in data.items()
        }

    def _save(self) -> None:
        data = {
            name: [f.tolist() for f in features]
            for name, features in self._people.items()
        }
        STORAGE_PATH.write_text(json.dumps(data, indent=2))

    def enroll(self, name: str, image: Image.Image, box) -> None:
        """Adds one more reference sample for `name`. Enrolling the same
        name more than once (e.g. seeing them again at a different angle
        or in different light) adds another sample rather than replacing
        the old one -- recognize() matches against ALL of a person's
        samples, so more samples usually means more reliable recognition,
        not less."""
        feature = _extract_feature(image, box)
        with self._lock:
            self._people.setdefault(name, []).append(feature)
            self._save()

    def forget(self, name: str) -> bool:
        """Returns True if `name` was known and is now removed."""
        with self._lock:
            if name in self._people:
                del self._people[name]
                self._save()
                return True
            return False

    def names(self) -> list:
        with self._lock:
            return sorted(self._people.keys())

    def recognize(self, image: Image.Image, box) -> Optional[str]:
        """Returns the best-matching enrolled name for the face at
        `box`, or None if nobody enrolled matches closely enough."""
        with self._lock:
            people = dict(self._people)
        if not people:
            return None

        recognizer = _get_recognizer()
        feature = _extract_feature(image, box)
        best_name = None
        best_score = MATCH_THRESHOLD
        for name, samples in people.items():
            for sample in samples:
                score = recognizer.match(feature, sample, cv2.FaceRecognizerSF_FR_COSINE)
                if score > best_score:
                    best_score = score
                    best_name = name
        return best_name


known_faces = KnownFaces()
