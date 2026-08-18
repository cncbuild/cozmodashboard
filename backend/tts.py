"""
Offline text-to-speech for "make Cozmo talk".

Cozmo himself has no text-to-speech built in -- the original app sent typed
text to Anki's cloud, which synthesized speech in Anki's own licensed voice
and streamed it back as audio. Since that cloud service is gone, we
synthesize speech locally instead and play the result through Cozmo's own
speaker.

Two different engines are used depending on OS, both fully offline:
  - Windows: `pyttsx3`, which uses Windows' built-in SAPI voices.
  - Linux: `piper-tts`, a neural TTS engine that ships as a plain pip
    package with everything it needs bundled in (including its own private
    phonemizer) -- deliberately NOT `pyttsx3`'s Linux backend, which shells
    out to a system-installed `espeak` binary. Endless OS's system files
    are read-only (no apt/sudo installs), so anything requiring a system
    package won't work there -- piper only touches this project's own venv
    and a downloaded voice model file, both in the user's home directory.

Neither engine sounds anything like a robot on its own -- ROBOT_VOICE_*
below is a hand-tuned effect (pitch/speed shift + ring modulation) built
from listening and adjusting, aimed at a low, gravelly, WALL-E-ish
character rather than Cozmo's own original voice (a specific licensed
voice Anki applied its own effect to, which we have no access to). Not a
reverse-engineered match to anything in particular -- the tunables are
right here if you want to adjust the character (see _apply_robot_voice).

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

# --- "Robot voice" effect tuning -------------------------------------------
# Set to False to hear the plain, unprocessed TTS voice (useful for judging
# how much the effect below is actually changing).
ROBOT_VOICE_ENABLED = True

# How much faster + higher-pitched the voice becomes (1.0 = unchanged,
# below 1.0 = slower/deeper). Speed and pitch move together here -- like
# playing a record at the wrong speed -- rather than shifting pitch alone.
ROBOT_VOICE_SPEED = 1.15

# Ring modulation: multiplies the voice by a low-frequency tone, which adds
# a buzzy, textured "robotic" quality on top. Lower MOD_FREQ_HZ leans more
# "wobbly/gritty"; higher leans more "metallic buzz". Higher MOD_DEPTH =
# more pronounced/less intelligible.
ROBOT_VOICE_MOD_FREQ_HZ = 25.0
ROBOT_VOICE_MOD_DEPTH = 0.45

# Nasal quality: boosts the frequency band where nasal resonance actually
# lives (not a pitch thing -- a real voice's formants, i.e. which
# frequencies are loudest, is what makes a voice sound "nasal" vs not) and
# cuts bass, since a nasal voice is thin on low end. NASAL_BOOST_GAIN /
# BASS_CUT_GAIN are straight multipliers (1.0 = no change, <1.0 = quieter).
NASAL_BOOST_LOW_HZ = 900.0
NASAL_BOOST_HIGH_HZ = 2400.0
NASAL_BOOST_GAIN = 3.2
BASS_CUT_HZ = 400.0
BASS_CUT_GAIN = 0.22
# -----------------------------------------------------------------------


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


def _wav_to_mono_samples(raw_frames: bytes, channels: int, sampwidth: int) -> np.ndarray:
    """Returns float32 samples, downmixed to mono, at whatever the
    original framerate was (caller handles resampling separately)."""
    if sampwidth == 2:
        samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32)
    elif sampwidth == 1:
        # 8-bit WAV samples are unsigned, centered at 128.
        samples = (np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) - 128.0) * 256.0
    else:
        raise ValueError(f"Unsupported TTS sample width: {sampwidth} bytes")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


def _resample(samples: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """Simple linear-interpolation resample. Good enough for short spoken
    phrases; not intended for music-quality audio."""
    if orig_rate == target_rate:
        return samples
    duration = len(samples) / orig_rate
    target_len = max(1, int(round(duration * target_rate)))
    old_positions = np.linspace(0, 1, num=len(samples), endpoint=False)
    new_positions = np.linspace(0, 1, num=target_len, endpoint=False)
    return np.interp(new_positions, old_positions, samples)


def _apply_nasal_eq(samples: np.ndarray, framerate: int) -> np.ndarray:
    """Boosts the nasal-formant frequency band and cuts bass -- see the
    NASAL_*/BASS_* constants above. This is a whole-buffer FFT filter
    (fine here since we process a full recorded phrase at once, not a
    live stream) rather than a real-time-style filter, so it's just:
    transform, scale each frequency bin, transform back."""
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / framerate)

    gain = np.ones_like(freqs)
    gain[(freqs >= NASAL_BOOST_LOW_HZ) & (freqs <= NASAL_BOOST_HIGH_HZ)] *= NASAL_BOOST_GAIN
    gain[freqs < BASS_CUT_HZ] *= BASS_CUT_GAIN

    return np.fft.irfft(spectrum * gain, n=len(samples))


def _apply_robot_voice(samples: np.ndarray, framerate: int) -> np.ndarray:
    """Pitch/speed-shifts, EQs, and ring-modulates `samples` (already at
    `framerate`) into the robot voice character. See the ROBOT_VOICE_*/
    NASAL_*/BASS_* constants above to adjust it."""

    # Speed + pitch shift together: resample the waveform onto fewer points
    # spanning the same original range, so it plays back faster/higher (or
    # slower/lower) at the SAME declared sample rate.
    if ROBOT_VOICE_SPEED != 1.0:
        new_len = max(1, int(len(samples) / ROBOT_VOICE_SPEED))
        old_indices = np.arange(len(samples))
        new_indices = np.linspace(0, len(samples) - 1, num=new_len)
        samples = np.interp(new_indices, old_indices, samples)

    samples = _apply_nasal_eq(samples, framerate)

    # Ring modulation for a buzzy, textured quality. The carrier can boost
    # amplitude by up to (1 + MOD_DEPTH), so scale down first to leave
    # enough headroom that modulation peaks don't clip against the
    # eventual int16 range.
    samples = samples / (1.0 + ROBOT_VOICE_MOD_DEPTH)
    t = np.arange(len(samples)) / framerate
    carrier = 1.0 + ROBOT_VOICE_MOD_DEPTH * np.sin(2 * np.pi * ROBOT_VOICE_MOD_FREQ_HZ * t)
    samples = samples * carrier

    # Final safety net: rather than hand-calculating exact headroom for
    # every combination of effects above (fragile -- easy to get subtly
    # wrong whenever a gain constant changes), just peak-normalize if
    # needed. NASAL_BOOST_GAIN in particular can push peaks well past the
    # eventual int16 range depending on the source audio.
    #
    # 30000, not something closer to int16's real max (32767): traced an
    # actual crash into pycozmo's own audio encoder (audio.py's
    # u_law_encoding) -- any sample with |value| >= ~31612 overflows its
    # encoding math past a valid byte (0-255) and raises ValueError. Not
    # something to work around by patching pycozmo; just never produce
    # samples that extreme in the first place.
    peak = np.abs(samples).max()
    safe_peak = 30000
    if peak > safe_peak:
        samples = samples * (safe_peak / peak)

    return samples


def _synthesize_raw_wav(text: str, out_path: pathlib.Path) -> None:
    """Runs the platform's TTS engine, writing whatever WAV format it
    natively produces to out_path -- format normalization and the robot
    voice effect happen separately, after this."""
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
    speaker (and, unless ROBOT_VOICE_ENABLED is False, processed to sound
    more like him), and returns its path. The caller is responsible for
    deleting the file (e.g. `path.unlink(missing_ok=True)`) once it's been
    played.
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

        samples = _wav_to_mono_samples(raw_frames, channels, sampwidth)
        samples = _resample(samples, framerate, TARGET_FRAMERATE)
        if ROBOT_VOICE_ENABLED:
            samples = _apply_robot_voice(samples, TARGET_FRAMERATE)
        samples = np.clip(samples, -32768, 32767).astype(np.int16)

        with wave.open(str(final_path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(TARGET_SAMPWIDTH)
            out.setframerate(TARGET_FRAMERATE)
            out.writeframes(samples.tobytes())
    finally:
        raw_path.unlink(missing_ok=True)

    return final_path
