"""Estimate a track's tempo (BPM) for the game's Meta.json.

The game normally has the player calibrate BPM on import; in fully-automatic mode
we estimate it with librosa instead. Estimates can land on a half/double "octave",
so we fold the result into a musically sane range. If a song still feels off in
game, it can be re-calibrated via the in-game BPM calibration screen.
"""
from __future__ import annotations

# Most Dead as Disco tracks sit roughly here; used to undo octave errors.
_LOW, _HIGH = 70.0, 180.0


def _fold(bpm: float) -> float:
    if bpm <= 0:
        return 0.0
    while bpm < _LOW:
        bpm *= 2
    while bpm > _HIGH:
        bpm /= 2
    return bpm


def estimate_tempo(audio_path: str) -> int | None:
    """Return an integer BPM estimate, or None if librosa is unavailable/fails."""
    try:
        import librosa
        import numpy as np
    except Exception as e:  # librosa not installed / numba issue
        print(f"[tempo] librosa unavailable ({e}); falling back to default tempo.")
        return None
    try:
        y, sr = librosa.load(audio_path, mono=True)
        # beat_track's tempo estimate is stable across librosa versions.
        estimate, _beats = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(estimate)[0])
        bpm = _fold(bpm)
        return int(round(bpm)) if bpm > 0 else None
    except Exception as e:
        print(f"[tempo] estimation failed ({e}); falling back to default tempo.")
        return None
