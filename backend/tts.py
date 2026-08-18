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

Neither engine sounds anything like a robot on its own -- everything below
VOICE_SETTINGS_SCHEMA is a hand-tuned effect (pitch/speed shift, vibrato,
nasal EQ, ring modulation) built from listening and adjusting, not a
reverse-engineered match to anything in particular. These are all
LIVE-ADJUSTABLE through the app itself (Voice Lab panel in the frontend,
backed by VoiceSettings below and the /api/voice-settings routes in
app.py) rather than fixed constants -- VOICE_SETTINGS_SCHEMA is the single
source of truth for what's adjustable, its label/grouping/range for the
UI, and its default value, so the frontend never hardcodes any of that.

Cozmo's speaker only accepts 16-bit PCM WAV audio at exactly 22050Hz or
48000Hz (see pycozmo.audio.load_wav). Whatever the TTS engine produces is
normalized to that here, so this keeps working even if the default voice
or model changes.
"""

import json
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

# --- Voice effect settings --------------------------------------------------
#
# Every numeric knob the robot voice effect has, in one place. Each entry:
#   "label": text shown in the frontend's Voice Lab panel
#   "group": which section of that panel it's grouped under
#   "min" / "max" / "step": slider range -- also used to validate updates
#     coming in over the API, so a bad value from a buggy client can't
#     produce a broken (e.g. divide-by-zero, absurd) audio effect
#   "default": value restored by the "reset to default" button/endpoint
#
# Add a new effect parameter by adding one entry here -- it automatically
# gets a slider in the UI and a validated API field, no frontend changes
# needed (same idea as animations.py for animation buttons).
VOICE_SETTINGS_SCHEMA = {
    "speed": {
        "label": "Pitch / Speed", "group": "Pitch",
        "min": 0.5, "max": 2.0, "step": 0.01, "default": 1.15,
    },
    "vibrato_rate_hz": {
        "label": "Wobble Speed", "group": "Vibrato",
        "min": 0.0, "max": 15.0, "step": 0.1, "default": 4.5,
    },
    "vibrato_depth": {
        "label": "Wobble Strength", "group": "Vibrato",
        "min": 0.0, "max": 0.6, "step": 0.01, "default": 0.18,
    },
    "mod_freq_hz": {
        "label": "Buzz Frequency", "group": "Buzz",
        "min": 5.0, "max": 100.0, "step": 1.0, "default": 25.0,
    },
    "mod_depth": {
        "label": "Buzz Strength", "group": "Buzz",
        "min": 0.0, "max": 1.0, "step": 0.01, "default": 0.45,
    },
    "nasal_boost_low_hz": {
        "label": "Nasal Range Start", "group": "Nasal",
        "min": 200.0, "max": 3000.0, "step": 10.0, "default": 900.0,
    },
    "nasal_boost_high_hz": {
        "label": "Nasal Range End", "group": "Nasal",
        "min": 500.0, "max": 6000.0, "step": 10.0, "default": 2400.0,
    },
    "nasal_boost_gain": {
        "label": "Nasal Strength", "group": "Nasal",
        "min": 1.0, "max": 6.0, "step": 0.1, "default": 3.2,
    },
    "bass_cut_hz": {
        "label": "Bass Cutoff", "group": "Nasal",
        "min": 50.0, "max": 1000.0, "step": 10.0, "default": 400.0,
    },
    "bass_cut_gain": {
        "label": "Bass Level", "group": "Nasal",
        "min": 0.0, "max": 1.0, "step": 0.01, "default": 0.22,
    },
}

# Persisted separately from the schema/defaults above -- this is where
# live-adjusted values actually live. Not committed to git (gitignored):
# it's a runtime preference file that'll keep changing as the voice gets
# tuned, not something that belongs in the project's source history.
STORAGE_PATH = pathlib.Path(__file__).parent / "voice_settings.json"


class VoiceSettings:
    """Holds the live (possibly user-adjusted) value of every effect
    parameter, plus the master on/off toggle. Read from TTS synthesis
    (possibly several threads at once -- /api/say and greeting reactions
    both run in background threads) and written from Flask request
    threads handling /api/voice-settings, hence the lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled = True
        self._values = {key: schema["default"] for key, schema in VOICE_SETTINGS_SCHEMA.items()}
        self._load()

    def _load(self) -> None:
        if not STORAGE_PATH.exists():
            return
        try:
            data = json.loads(STORAGE_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            return  # corrupt/unreadable -- just fall back to defaults
        if "enabled" in data and isinstance(data["enabled"], bool):
            self._enabled = data["enabled"]
        for key, value in data.get("values", {}).items():
            if key in VOICE_SETTINGS_SCHEMA:
                self._values[key] = value

    def _save(self) -> None:
        STORAGE_PATH.write_text(json.dumps({"enabled": self._enabled, "values": self._values}, indent=2))

    def snapshot(self) -> dict:
        """A consistent point-in-time copy of every current value, for a
        single synthesis call to use throughout (so a setting changing
        mid-request can't partially apply)."""
        with self._lock:
            return {"enabled": self._enabled, **self._values}

    def as_dict(self) -> dict:
        with self._lock:
            return {"enabled": self._enabled, "values": dict(self._values)}

    def update(self, enabled=None, values: dict = None) -> list:
        """Applies validated changes; returns a list of human-readable
        error messages for anything rejected (unknown key, wrong type,
        out of range) -- valid changes still apply even if others in the
        same call are rejected."""
        errors = []
        with self._lock:
            if enabled is not None:
                if isinstance(enabled, bool):
                    self._enabled = enabled
                else:
                    errors.append("enabled must be true or false")

            for key, raw_value in (values or {}).items():
                schema = VOICE_SETTINGS_SCHEMA.get(key)
                if schema is None:
                    errors.append(f"Unknown voice setting: {key!r}")
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    errors.append(f"{key} must be a number")
                    continue
                if not (schema["min"] <= value <= schema["max"]):
                    errors.append(f"{key} must be between {schema['min']} and {schema['max']}")
                    continue
                self._values[key] = value

            self._save()
        return errors

    def reset(self) -> None:
        with self._lock:
            self._enabled = True
            self._values = {key: schema["default"] for key, schema in VOICE_SETTINGS_SCHEMA.items()}
            self._save()


voice_settings = VoiceSettings()
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


def _apply_nasal_eq(samples: np.ndarray, framerate: int, settings: dict) -> np.ndarray:
    """Boosts the nasal-formant frequency band and cuts bass. This is a
    whole-buffer FFT filter (fine here since we process a full recorded
    phrase at once, not a live stream) rather than a real-time-style
    filter, so it's just: transform, scale each frequency bin, transform
    back."""
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / framerate)

    gain = np.ones_like(freqs)
    nasal_band = (freqs >= settings["nasal_boost_low_hz"]) & (freqs <= settings["nasal_boost_high_hz"])
    gain[nasal_band] *= settings["nasal_boost_gain"]
    gain[freqs < settings["bass_cut_hz"]] *= settings["bass_cut_gain"]

    return np.fft.irfft(spectrum * gain, n=len(samples))


def _pitch_shift_with_vibrato(samples: np.ndarray, framerate: int, settings: dict) -> np.ndarray:
    """
    Speed/pitch-shifts by settings["speed"] (like a record played at the
    wrong speed), with a periodic wobble added on top (vibrato_rate_hz/
    vibrato_depth) so the pitch rises and falls over the phrase instead
    of staying perfectly constant -- a constant shift alone doesn't add
    any variation over time, however it's tuned, which reads as flat/
    monotone rather than animated/expressive. Implemented as a
    variable-rate resample: at each output sample, how far to advance
    through the input oscillates around the base rate rather than being
    fixed.
    """
    speed = settings["speed"]
    new_len = max(1, int(len(samples) / speed))
    if new_len < 2 or len(samples) < 2:
        return samples

    base_step = (len(samples) - 1) / (new_len - 1)
    t = np.arange(new_len) / framerate
    wobble = 1.0 + settings["vibrato_depth"] * np.sin(2 * np.pi * settings["vibrato_rate_hz"] * t)
    step = base_step * wobble

    # Cumulative sum of per-sample steps = position to read from in the
    # input at each output sample; shifted so the first output sample
    # reads from the very start of the input rather than one step in.
    input_position = np.cumsum(step) - step[0]
    input_position = np.clip(input_position, 0, len(samples) - 1)

    old_indices = np.arange(len(samples))
    return np.interp(input_position, old_indices, samples)


def _apply_robot_voice(samples: np.ndarray, framerate: int, settings: dict) -> np.ndarray:
    """Pitch/speed-shifts (with vibrato), EQs, and ring-modulates
    `samples` (already at `framerate`) into the robot voice character,
    using the given settings snapshot (see VoiceSettings.snapshot)."""

    if settings["speed"] != 1.0 or settings["vibrato_depth"] != 0.0:
        samples = _pitch_shift_with_vibrato(samples, framerate, settings)

    samples = _apply_nasal_eq(samples, framerate, settings)

    # Ring modulation for a buzzy, textured quality. The carrier can boost
    # amplitude by up to (1 + mod_depth), so scale down first to leave
    # enough headroom that modulation peaks don't clip against the
    # eventual int16 range.
    mod_depth = settings["mod_depth"]
    samples = samples / (1.0 + mod_depth)
    t = np.arange(len(samples)) / framerate
    carrier = 1.0 + mod_depth * np.sin(2 * np.pi * settings["mod_freq_hz"] * t)
    samples = samples * carrier

    # Final safety net: rather than hand-calculating exact headroom for
    # every combination of effects above (fragile -- easy to get subtly
    # wrong whenever a gain constant changes, and now that these are
    # user-adjustable at runtime, a hand-derived margin could be wrong
    # for some combination no one's tried yet), just peak-normalize.
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
    speaker (and, unless voice_settings currently has the effect
    disabled, processed into the robot voice), and returns its path. The
    caller is responsible for deleting the file (e.g.
    `path.unlink(missing_ok=True)`) once it's been played.
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

        settings = voice_settings.snapshot()
        if settings["enabled"]:
            samples = _apply_robot_voice(samples, TARGET_FRAMERATE, settings)

        samples = np.clip(samples, -32768, 32767).astype(np.int16)

        with wave.open(str(final_path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(TARGET_SAMPWIDTH)
            out.setframerate(TARGET_FRAMERATE)
            out.writeframes(samples.tobytes())
    finally:
        raw_path.unlink(missing_ok=True)

    return final_path
