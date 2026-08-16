"""
Offline text-to-speech for "make Cozmo talk".

Cozmo himself has no text-to-speech built in -- the original app sent typed
text to Anki's cloud, which synthesized speech and streamed it back as
audio. Since that cloud service is gone, we synthesize speech locally with
`pyttsx3` (uses Windows' built-in SAPI voices -- no internet, no account)
and then play the resulting audio through Cozmo's own speaker.

Cozmo's speaker only accepts 16-bit PCM WAV audio at exactly 22050Hz or
48000Hz (see pycozmo.audio.load_wav). Whatever `pyttsx3` happens to produce
is normalized to 22050Hz/16-bit/mono here so this keeps working even if the
system's default voice changes, or if this ever runs on a different OS
where the TTS engine behaves differently (e.g. espeak on Linux).
"""

import pathlib
import tempfile
import threading
import wave

import numpy as np
import pyttsx3

# pyttsx3 engines wrap a COM object on Windows (SAPI) that is not safe to
# share or call into from multiple threads at once. Flask can serve
# concurrent requests on different threads, so we serialize all TTS work
# through this lock rather than trying to share one long-lived engine.
_tts_lock = threading.Lock()

TARGET_FRAMERATE = 22050
TARGET_SAMPWIDTH = 2  # bytes (16-bit)


def _resample_to_target(raw_frames: bytes, channels: int, sampwidth: int, framerate: int) -> bytes:
    """Convert arbitrary PCM audio to mono 16-bit PCM at TARGET_FRAMERATE."""

    if sampwidth == 2:
        samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        # 8-bit WAV samples are unsigned, centered at 128.
        samples = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    else:
        raise ValueError(f"Unsupported TTS sample width: {sampwidth} bytes")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if framerate != TARGET_FRAMERATE:
        duration = len(samples) / framerate
        target_len = max(1, int(round(duration * TARGET_FRAMERATE)))
        # Simple linear-interpolation resample. Good enough for short
        # spoken phrases; not intended for music-quality audio.
        old_positions = np.linspace(0, 1, num=len(samples), endpoint=False)
        new_positions = np.linspace(0, 1, num=target_len, endpoint=False)
        samples = np.interp(new_positions, old_positions, samples)

    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()


def synthesize_speech_wav(text: str) -> pathlib.Path:
    """
    Synthesizes `text` to a temporary WAV file formatted for Cozmo's
    speaker, and returns its path. The caller is responsible for deleting
    the file (e.g. `path.unlink(missing_ok=True)`) once it's been played.
    """
    raw_path = pathlib.Path(tempfile.mktemp(suffix=".wav"))
    final_path = pathlib.Path(tempfile.mktemp(suffix=".wav"))

    with _tts_lock:
        engine = pyttsx3.init()
        try:
            engine.save_to_file(text, str(raw_path))
            engine.runAndWait()
        finally:
            engine.stop()

    try:
        with wave.open(str(raw_path), "rb") as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            framerate = w.getframerate()
            raw_frames = w.readframes(w.getnframes())

        if sampwidth == TARGET_SAMPWIDTH and channels == 1 and framerate in (22050, 48000):
            # Already in a format Cozmo accepts directly -- no conversion needed.
            final_path.write_bytes(raw_path.read_bytes())
        else:
            converted = _resample_to_target(raw_frames, channels, sampwidth, framerate)
            with wave.open(str(final_path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(TARGET_SAMPWIDTH)
                out.setframerate(TARGET_FRAMERATE)
                out.writeframes(converted)
    finally:
        raw_path.unlink(missing_ok=True)

    return final_path
