"""
Offline text-to-speech for "make Cozmo talk".

Cozmo himself has no text-to-speech built in -- the original app sent typed
text to Anki's cloud, which synthesized speech and streamed it back as
audio. Since that cloud service is gone, we synthesize speech locally and
play the resulting audio through Cozmo's own speaker.

Two different engines are used depending on OS, both fully offline:
  - Windows: `pyttsx3`, which uses Windows' built-in SAPI voices.
  - Linux: `piper-tts`, a neural TTS engine that ships as a plain pip
    package with everything it needs bundled in (including its own private
    phonemizer) -- deliberately NOT `pyttsx3`'s Linux backend, which shells
    out to a system-installed `espeak` binary. Endless OS's system files
    are read-only (no apt/sudo installs), so anything requiring a system
    package won't work there -- piper only touches this project's own venv
    and a downloaded voice model file, both in the user's home directory.

Cozmo's speaker only accepts 16-bit PCM WAV audio at exactly 22050Hz or
48000Hz (see pycozmo.audio.load_wav). Whatever the TTS engine produces is
normalized to that here, so this keeps working even if the default voice
or model changes.
"""

import pathlib
import sys
import tempfile
import threading
import wave

import numpy as np

_tts_lock = threading.Lock()

TARGET_FRAMERATE = 22050
TARGET_SAMPWIDTH = 2  # bytes (16-bit)

# Where setup_linux.sh downloads the Piper voice model to (see that script
# and README.md). Only used on Linux.
PIPER_VOICE_NAME = "en_US-lessac-medium"
PIPER_VOICE_PATH = pathlib.Path(__file__).parent.parent / "voices" / f"{PIPER_VOICE_NAME}.onnx"

_piper_voice = None  # lazily loaded, see _get_piper_voice()


def _get_piper_voice():
    global _piper_voice
    if _piper_voice is None:
        from piper import PiperVoice
        if not PIPER_VOICE_PATH.exists():
            raise RuntimeError(
                f"Piper voice model not found at {PIPER_VOICE_PATH}. "
                "Run setup_linux.sh again -- it downloads this as part of setup."
            )
        _piper_voice = PiperVoice.load(str(PIPER_VOICE_PATH))
    return _piper_voice


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


def _synthesize_raw_wav(text: str, out_path: pathlib.Path) -> None:
    """Runs the platform's TTS engine, writing whatever WAV format it
    natively produces to out_path -- format normalization happens
    separately, after this."""
    if sys.platform == "win32":
        import pyttsx3
        # pyttsx3 wraps a COM object on Windows (SAPI) that isn't safe to
        # share or call into from multiple threads at once. Flask can serve
        # concurrent requests on different threads, so we serialize all TTS
        # work through the module-level lock rather than sharing an engine.
        engine = pyttsx3.init()
        try:
            engine.save_to_file(text, str(out_path))
            engine.runAndWait()
        finally:
            engine.stop()
    else:
        voice = _get_piper_voice()
        with wave.open(str(out_path), "wb") as w:
            voice.synthesize_wav(text, w)


def synthesize_speech_wav(text: str) -> pathlib.Path:
    """
    Synthesizes `text` to a temporary WAV file formatted for Cozmo's
    speaker, and returns its path. The caller is responsible for deleting
    the file (e.g. `path.unlink(missing_ok=True)`) once it's been played.
    """
    raw_path = pathlib.Path(tempfile.mktemp(suffix=".wav"))
    final_path = pathlib.Path(tempfile.mktemp(suffix=".wav"))

    with _tts_lock:
        _synthesize_raw_wav(text, raw_path)

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
